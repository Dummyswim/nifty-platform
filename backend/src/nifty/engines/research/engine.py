"""Engine `research.distance_entry_v1` (index-only, paper only, no option P&L here).

On every finalized 1m bar: features -> (a) fill a pending entry at THIS bar's open (signal was the
previous close), (b) advance an open position through `step_bar`, (c) look for a new signal (a named
baseline or the armed-resumption machine). One position at a time. Units: points and R only."""

from typing import Any

from nifty.contracts import Bar, EngineOutput, Ev, PlotSpec, TradeRecord
from nifty.engines.base import register_engine
from nifty.engines.context import ConfigError, EngineContext
from nifty.engines.pinekit import bar_minutes_ist, is_last_bar_of_session
from nifty.engines.research.armed import ArmedMachine
from nifty.engines.research.baselines import BASELINES
from nifty.engines.research.features import Features, FeatureState
from nifty.engines.research.outcomes import Position
from nifty.engines.research.params import ResearchParams


def _hm(hm: int) -> int:
    return hm // 100 * 60 + hm % 100


def _f(x: float | None, nd: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


class ResearchEngine:
    id = "research.distance_entry_v1"
    version = "1"
    default_timeframe = "1m"
    Params = ResearchParams
    plots = [
        PlotSpec(name="ema_fast", role="info", pane="overlay"),
        PlotSpec(name="ema_slow", role="neutral", pane="overlay"),
        PlotSpec(name="anchor", role="warn", pane="overlay"),
        *[PlotSpec(name=n, role="hidden", pane="own") for n in ("d", "e", "m", "anchor_rate", "gap_rate", "a")],
    ]  # fmt: skip
    warmup_bars = 60

    def __init__(self, params: ResearchParams, ctx: EngineContext) -> None:
        if params.trigger_mode == "intrabar":
            raise ConfigError(
                "intrabar triggering needs lower-timeframe or tick evidence; the 1m chart has none"
            )
        if params.pullback_min > params.pullback_max:
            raise ConfigError("pullback_min must not exceed pullback_max")
        self.p, self.ctx = params, ctx
        self.feats = FeatureState(params)
        self.machine = ArmedMachine(params)
        self.pos: Position | None = None
        self.pending: dict[str, Any] | None = None  # {"side", "signal_start"}
        self.n = 0
        self.last_start: str | None = None
        self.snap_panel: dict[str, Any] | None = None
        self.t_start, self.t_end = _hm(params.entry_start_hm), _hm(params.entry_end_hm)

    # ---- helpers -----------------------------------------------------------------------------
    def _in_window(self, bar: Bar) -> bool:
        return self.t_start <= bar_minutes_ist(bar.bar_start_utc) <= self.t_end

    def _signal(self, x: Features, bar: Bar, out: EngineOutput) -> int:
        if self.p.baseline == "armed_resumption":
            side, trs = self.machine.on_bar(bar, self.n, x.prev_p, x.sign, x.new_session)
            for t in trs:
                out.events.append(
                    Ev(f"research.{t.kind}", {**t.payload, "baseline": self.p.baseline}, "close")
                )
            return side
        return BASELINES[self.p.baseline](x)

    # ---- per bar -----------------------------------------------------------------------------
    def on_bar(self, bar: Bar) -> EngineOutput:
        out = EngineOutput()
        if self.last_start is not None and bar.bar_start_utc.isoformat() <= self.last_start:
            return out  # duplicate or out-of-order bar: never processed twice
        self.last_start = bar.bar_start_utc.isoformat()
        self.n += 1
        p = self.p
        x = self.feats.update(
            bar, self.ctx.calendar, self.ctx.proxy_volume(bar) if p.anchor_proxy else None
        )
        # (a) fill the pending entry at this bar's open, if the window allows
        if self.pending is not None:
            pend, self.pending = self.pending, None
            if x.new_session:
                out.events.append(
                    Ev(
                        "research.invalidated",
                        {"reason": "session", "baseline": p.baseline},
                        "open",
                    )
                )
            elif not self._in_window(bar):
                out.events.append(
                    Ev("research.invalidated", {"reason": "window", "baseline": p.baseline}, "open")
                )
            else:
                import datetime as _dt

                self.pos = Position(
                    pend["side"], bar.open, bar.bar_start_utc, _dt.datetime.fromisoformat(pend["signal_start"]),
                    p.stop_pts, p.target_pts, p.max_hold_bars, p.cost_pts,
                )  # fmt: skip
                out.events.append(
                    Ev("research.entry", {"side": "long" if pend["side"] > 0 else "short", "baseline": p.baseline,
                                          "signal_bar_start": pend["signal_start"], "entry_px": bar.open,
                                          "stop_px": self.pos.stop, "target_px": self.pos.target,
                                          "target_pts": p.target_pts, "stop_pts": p.stop_pts}, "open")
                )  # fmt: skip
        # (b) advance an open position (the entry bar may exit)
        if self.pos is not None:
            res = self.pos.on_bar(bar, is_last_bar_of_session(bar, self.ctx.calendar))
            if res is not None:
                pos, self.pos = self.pos, None
                net_r = res.net_pts / p.stop_pts
                out.trades.append(
                    TradeRecord(
                        trade_id=f"{self.id}:{pos.entry_time.isoformat()}", engine_id=self.id,
                        instrument_id=bar.instrument_id, side="long" if pos.side > 0 else "short",
                        signal_bar_start=pos.signal_start, entry_time=pos.entry_time, entry_px=pos.entry_px,
                        exit_time=res.exit_time, exit_px=res.exit_px, exit_reason=res.outcome,
                        gross_pts=res.gross_pts, cost_pts=p.cost_pts, net_pts=res.net_pts, r_multiple=net_r,
                        mae_pts=res.mae_pts, mfe_pts=res.mfe_pts, bars_held=res.bars_held,
                        execution_mode="conservative", flags=res.flags,
                    )
                )  # fmt: skip
                out.events.append(
                    Ev("research.exit", {
                        "outcome": res.outcome, "side": "long" if pos.side > 0 else "short",
                        "exit_px": res.exit_px, "gross_pts": res.gross_pts, "net_pts": res.net_pts, "r": net_r,
                        "mae_pts": res.mae_pts, "mfe_pts": res.mfe_pts, "bars_held": res.bars_held,
                        "first_minute_adverse_pts": res.first_minute_adverse_pts, "drawdown_pts": res.drawdown_pts,
                        "time_to_barrier_bars": res.time_to_barrier_bars, "containing_bar_start": res.containing_bar_start.isoformat(),
                        "flags": res.flags, "baseline": p.baseline,
                    }, "close" if res.outcome == "TIME_EXIT" else "open")
                )  # fmt: skip
        # (c) a new signal, only when flat
        if self.pos is None and self.pending is None:
            side = self._signal(x, bar, out)
            if side:
                self.pending = {"side": side, "signal_start": bar.bar_start_utc.isoformat()}
        elif p.baseline == "armed_resumption":
            self.machine.reset(None)
        out.plots = {
            "ema_fast": x.f, "ema_slow": x.s, "anchor": x.v, "d": x.d, "e": x.e, "m": x.m,
            "anchor_rate": x.anchor_rate, "gap_rate": x.gap_rate, "a": x.a,
        }  # fmt: skip
        self.snap_panel = {k: (None if getattr(x, k) != getattr(x, k) else getattr(x, k)) for k in
                           ("d", "e", "m", "anchor_rate", "gap_rate", "a", "p", "f", "s", "v")} | {"anchor_kind": x.anchor_kind}  # fmt: skip
        return out

    def on_provisional(self, bar: Bar) -> EngineOutput:
        return EngineOutput()  # completed-close baselines only

    def panel(self) -> dict[str, Any] | None:
        r = self.snap_panel
        if r is None:
            return None
        state = (
            "in trade"
            if self.pos
            else "entry pending"
            if self.pending
            else ("armed" if self.machine.armed else "flat")
        )
        rows = [
            ("Baseline", self.p.baseline, "neutral"), ("State", state, "neutral"),
            ("D (P-V)/A", _f(r["d"]), "neutral"), ("E (P-F)/A", _f(r["e"]), "neutral"),
            ("M (F-S)/A", _f(r["m"]), "neutral"), ("Anchor rate / bar", _f(r["anchor_rate"], 3), "neutral"),
            ("Gap rate / bar", _f(r["gap_rate"], 3), "neutral"), ("A (prior ATR, pts)", _f(r["a"]), "neutral"),
            ("Anchor", r["anchor_kind"], "neutral"),
        ]  # fmt: skip
        return {"rows": [{"label": a, "value": b, "role": c} for a, b, c in rows]}

    def snapshot(self) -> dict[str, Any]:
        return {
            "v": 1, "feats": self.feats.state(), "machine": self.machine.state(),
            "pos": self.pos.state() if self.pos else None, "pending": self.pending, "n": self.n,
            "last_start": self.last_start, "panel": self.snap_panel,
        }  # fmt: skip

    def restore(self, snap: dict[str, Any]) -> None:
        self.feats.load(snap["feats"])
        self.machine.load(snap["machine"])
        self.pos = Position.from_state(snap["pos"]) if snap["pos"] else None
        self.pending, self.n, self.last_start, self.snap_panel = (
            snap["pending"],
            snap["n"],
            snap["last_start"],
            snap["panel"],
        )


register_engine(ResearchEngine, ready=True)
