"""Position tracking and outcomes via `execution.barriers.step_bar` (conservative mode, spec/03).

Entry is the NEXT bar's open; stop and target are anchored to that actual open. The entry bar may
exit. Outcomes: TARGET_FIRST | STOP_FIRST | TIME_EXIT (actual directional return at the close of the
last allowed bar; `max_hold_bars` counts from the entry bar inclusive). Both barriers inside one bar
=> STOP_FIRST + `ambiguous_bar`. Interruptions (session cut, gaps in the bar series) are flagged and
stay in every denominator. Metric definitions (OHLC-only, so path-resolution limited):
- mae_pts / mfe_pts: worst adverse / best favourable excursion over the trade's bars (clipped at the exit).
- first_minute_adverse_pts: adverse excursion on the entry bar.
- drawdown_pts: largest fall of unrealised P&L from its running peak, measured on bar CLOSES.
- time_to_barrier_bars: bars held up to and including the exit bar (None for a time exit).
- exit_time of a barrier exit is the CONTAINING bar's start (exact fill time unknown)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from nifty.contracts import Bar
from nifty.execution.barriers import step_bar

OUTCOME = {"STOP": "STOP_FIRST", "TARGET": "TARGET_FIRST"}


@dataclass
class Resolved:
    outcome: str
    exit_px: float
    exit_time: datetime
    containing_bar_start: datetime
    gross_pts: float
    net_pts: float
    mae_pts: float
    mfe_pts: float
    bars_held: int
    first_minute_adverse_pts: float
    drawdown_pts: float
    time_to_barrier_bars: int | None
    flags: list[str] = field(default_factory=list)


class Position:
    def __init__(
        self, side: int, entry_px: float, entry_time: datetime, signal_start: datetime,
        stop_pts: float, target_pts: float, max_hold: int, cost_pts: float,
    ) -> None:  # fmt: skip
        self.side, self.entry_px, self.entry_time, self.signal_start = (
            side,
            entry_px,
            entry_time,
            signal_start,
        )
        self.stop = entry_px - side * stop_pts
        self.target = entry_px + side * target_pts
        self.max_hold, self.cost = max_hold, cost_pts
        self.bars = 0
        self.mae = self.mfe = self.first_adv = self.peak = self.dd = 0.0
        self.flags: list[str] = []
        self.prev_end: datetime | None = None

    def on_bar(self, bar: Bar, session_end: bool) -> Resolved | None:
        if (
            self.prev_end is not None
            and bar.bar_start_utc > self.prev_end
            and "data_gap" not in self.flags
        ):
            self.flags.append("data_gap")
        self.prev_end = bar.bar_end_utc
        out = step_bar(
            "long" if self.side > 0 else "short",
            self.entry_px,
            self.stop,
            self.target,
            bar,
            "conservative",
        )
        self.bars += 1
        self.mae, self.mfe = max(self.mae, out.mae), max(self.mfe, out.mfe)
        if self.bars == 1:
            self.first_adv = out.mae
        for f in out.flags:
            if f not in self.flags:
                self.flags.append(f)
        if out.reason is not None:
            return self._done(OUTCOME[out.reason], out.px, bar.bar_start_utc, bar, self.bars)
        unreal = self.side * (bar.close - self.entry_px)
        self.peak = max(self.peak, unreal)
        self.dd = max(self.dd, self.peak - unreal)
        if self.bars >= self.max_hold or session_end:
            if session_end and self.bars < self.max_hold:
                self.flags.append("session_cut")
            return self._done("TIME_EXIT", bar.close, bar.bar_end_utc, bar, None)
        return None

    def _done(self, outcome: str, px: float, when: datetime, bar: Bar, ttb: int | None) -> Resolved:
        gross = self.side * (px - self.entry_px)
        return Resolved(
            outcome, px, when, bar.bar_start_utc, gross, gross - self.cost, self.mae, self.mfe, self.bars,
            self.first_adv, self.dd, ttb, list(self.flags),
        )  # fmt: skip

    def state(self) -> dict[str, Any]:
        return {
            "side": self.side, "entry_px": self.entry_px, "entry_time": self.entry_time.isoformat(),
            "signal_start": self.signal_start.isoformat(), "stop": self.stop, "target": self.target,
            "max_hold": self.max_hold, "cost": self.cost, "bars": self.bars, "mae": self.mae,
            "mfe": self.mfe, "first_adv": self.first_adv, "peak": self.peak, "dd": self.dd,
            "flags": list(self.flags), "prev_end": self.prev_end.isoformat() if self.prev_end else None,
        }  # fmt: skip

    @staticmethod
    def from_state(st: dict[str, Any]) -> "Position":
        p = Position(
            st["side"], st["entry_px"], datetime.fromisoformat(st["entry_time"]),
            datetime.fromisoformat(st["signal_start"]), 0.0, 0.0, st["max_hold"], st["cost"],
        )  # fmt: skip
        p.stop, p.target, p.bars, p.mae, p.mfe = (
            st["stop"],
            st["target"],
            st["bars"],
            st["mae"],
            st["mfe"],
        )
        p.first_adv, p.peak, p.dd, p.flags = (
            st["first_adv"],
            st["peak"],
            st["dd"],
            list(st["flags"]),
        )
        p.prev_end = datetime.fromisoformat(st["prev_end"]) if st["prev_end"] else None
        return p
