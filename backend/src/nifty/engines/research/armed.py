"""Armed-resumption state machine (docs/engines/research-armed.md). Pure and JSON-serialisable."""

from dataclasses import dataclass, field
from typing import Any

from nifty.contracts import Bar
from nifty.engines.research.params import ResearchParams


def _n(x: float) -> float | None:
    return None if x != x else x


@dataclass
class Transition:
    kind: str  # watch | armed | invalidated
    payload: dict[str, Any] = field(default_factory=dict)


class ArmedMachine:
    def __init__(self, p: ResearchParams) -> None:
        self.p = p
        self.sign = 0
        self.run: list[tuple[float, float]] = []  # (high, low) of the current pullback run
        self.armed = False
        self.side = 0
        self.trigger = self.inval = float("nan")
        self.armed_n = 0
        self.arms_used = 0
        self.watched = False

    def reset(self, reason: str | None = None) -> list[Transition]:
        out = (
            [Transition("invalidated", {"reason": reason, "side": self.side})]
            if self.armed and reason
            else []
        )
        self.run, self.armed, self.side, self.arms_used, self.watched = [], False, 0, 0, False
        self.trigger = self.inval = float("nan")
        return out

    def on_bar(
        self, bar: Bar, n: int, prev_close: float, sign: int, new_session: bool
    ) -> tuple[int, list[Transition]]:  # fmt: skip
        """One completed bar. Returns (entry side or 0, transitions). `n` is the bar counter."""
        p, out = self.p, []
        if new_session:
            out += self.reset("session")
        elif sign != self.sign:
            out += self.reset("regime_flip")
        self.sign = sign
        if sign == 0 or prev_close != prev_close:
            return 0, out
        s, c = sign, bar.close
        if (
            self.armed
        ):  # (1) invalidation, trigger, expiry; the arming bar itself is never evaluated
            beyond_inv = c < self.inval if s > 0 else c > self.inval
            hit = c > self.trigger if s > 0 else c < self.trigger
            if beyond_inv:
                out.append(self._end("invalidation"))
            elif hit:
                side = s
                self.armed, self.arms_used, self.run, self.watched = False, 0, [], False
                return side, out
            elif n - self.armed_n >= p.arm_expiry_bars:
                out.append(self._end("expired"))
            return 0, out
        against = c < prev_close if s > 0 else c > prev_close  # a pullback bar by CLOSE, not colour
        if against:
            self.run.append((bar.high, bar.low))
            if len(self.run) > p.pullback_max:
                self.run, self.watched = [], False
            elif len(self.run) >= p.pullback_min and not self.watched:
                self.watched = True
                out.append(Transition("watch", {"side": s, "bars": len(self.run)}))
            return 0, out
        run, self.run, was_watched, self.watched = self.run, [], self.watched, False
        resumes = c > prev_close if s > 0 else c < prev_close
        if not (resumes and p.pullback_min <= len(run) <= p.pullback_max) or not was_watched:
            return 0, out
        if self.arms_used >= 1 + p.max_rearms:
            return 0, out  # locked until the context flips, a new session or a completed trade
        trig = max(h for h, _ in run) if s > 0 else min(lo for _, lo in run)
        inv = min(lo for _, lo in run) if s > 0 else max(h for h, _ in run)
        if abs(trig - inv) > p.stop_pts:  # cannot respect the risk budget: skip, never widen
            out.append(
                Transition(
                    "invalidated",
                    {"reason": "risk_budget", "side": s, "trigger": trig, "invalidation": inv},
                )
            )
            self.arms_used += 1
            return 0, out
        self.armed, self.side, self.trigger, self.inval, self.armed_n = True, s, trig, inv, n
        self.arms_used += 1
        out.append(
            Transition(
                "armed",
                {
                    "side": s,
                    "trigger": trig,
                    "invalidation": inv,
                    "expiry_bar": n + p.arm_expiry_bars,
                    "arm": self.arms_used,
                },
            )
        )
        return 0, out

    def _end(self, reason: str) -> Transition:
        t = Transition(
            "invalidated",
            {
                "reason": reason,
                "side": self.side,
                "trigger": self.trigger,
                "invalidation": self.inval,
            },
        )
        self.armed = False
        return t

    def state(self) -> dict[str, Any]:
        return {
            "sign": self.sign, "run": [list(r) for r in self.run], "armed": self.armed,
            "side": self.side, "trigger": _n(self.trigger), "inval": _n(self.inval),
            "armed_n": self.armed_n, "arms_used": self.arms_used, "watched": self.watched,
        }  # fmt: skip

    def load(self, st: dict[str, Any]) -> None:
        self.sign, self.run, self.armed, self.side = (
            st["sign"],
            [(h, lo) for h, lo in st["run"]],
            st["armed"],
            st["side"],
        )
        self.trigger = float("nan") if st["trigger"] is None else st["trigger"]
        self.inval = float("nan") if st["inval"] is None else st["inval"]
        self.armed_n, self.arms_used, self.watched = st["armed_n"], st["arms_used"], st["watched"]
