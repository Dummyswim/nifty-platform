"""Step 12 (L696-755): zone sweeps as small state machines (v2.2 confirmed sweeps). The sweep bar is
armed, never evaluated itself; the confirm window is bars +1..+sweepConfBars; a bar that cancels may
re-arm; each zone centre confirms once per session (`done`, tolerance 0.7 * ATR). Marks land on the
CONFIRMING bar."""

import math
from typing import Any

from nifty.contracts import Ev, OverlayElement, PlotSpec
from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.steps import PLOT_SPECS, BarFrame, register_slot, step

NaN = math.nan
PLOT_SPECS += [PlotSpec(name="sweep_d_conf", pane="own"), PlotSpec(name="sweep_s_conf", pane="own")]


def _enc(v: float) -> float | None:
    return None if v != v else v


def _dec(v: float | None) -> float:
    return NaN if v is None else v


class Side:
    def __init__(self) -> None:
        self.c = NaN  # zone centre
        self.edge = NaN  # demand: zone bot, supply: zone top
        self.x = NaN  # demand: sweep bar high, supply: sweep bar low
        self.bar: int | None = None  # bar index of the sweep bar (None = no pending sweep)
        self.done: list[float] = []

    def reset(self) -> None:
        self.bar = None
        self.done.clear()

    def state(self) -> dict[str, Any]:
        return {
            "c": _enc(self.c),
            "edge": _enc(self.edge),
            "x": _enc(self.x),
            "bar": self.bar,
            "done": list(self.done),
        }

    def load(self, st: dict[str, Any]) -> None:
        self.c, self.edge, self.x = _dec(st["c"]), _dec(st["edge"]), _dec(st["x"])
        self.bar, self.done = st["bar"], list(st["done"])


class Sweeps:
    def __init__(self) -> None:
        self.d, self.s = Side(), Side()

    def state(self) -> dict[str, Any]:
        return {"d": self.d.state(), "s": self.s.state()}

    def load(self, st: dict[str, Any]) -> None:
        self.d.load(st["d"])
        self.s.load(st["s"])


@register_slot("sweeps")
def make_sweeps(p: BaluParams) -> Sweeps:
    return Sweeps()


def far_from_all(done: list[float], v: float, tol: float) -> bool:
    return all(abs(d - v) > tol for d in done)


def advance(side: Side, demand: bool, bar_i: int, close: float, conf_bars: int) -> bool:
    """(a) cancel or confirm a pending sweep. Returns True when it confirmed."""
    if side.bar is None:
        return False
    broke = close < side.edge if demand else close > side.edge
    if broke or bar_i - side.bar > conf_bars:
        side.bar = None
        return False
    if (close > side.x) if demand else (close < side.x):
        side.done.append(side.c)
        side.bar = None
        return True
    return False


@step(12)
def sweeps(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    sw: Sweeps = eng.slots["sweeps"]
    s = eng.slots["core"].s
    loc, fp = f.extra["location"], f.extra["fp"]
    bar = f.bar
    if f.new_session:
        sw.d.reset()
        sw.s.reset()
    rng = max(bar.high - bar.low, eng.ctx.mintick)
    up_wick = (bar.high - max(bar.open, bar.close)) / rng
    dn_wick = (min(bar.open, bar.close) - bar.low) / rng
    sweep_d = (
        loc.tap_demand_bot == loc.tap_demand_bot
        and bar.low < loc.tap_demand_bot
        and bar.close > loc.tap_demand_bot
        and dn_wick >= 0.2
    )  # noqa: E501
    sweep_s = (
        loc.tap_supply_top == loc.tap_supply_top
        and bar.high > loc.tap_supply_top
        and bar.close < loc.tap_supply_top
        and up_wick >= 0.2
    )  # noqa: E501
    centre_d, centre_s = sw.d.c, sw.s.c  # the zone being confirmed this bar (before any re-arm)
    conf_d = advance(sw.d, True, s.n_bars, bar.close, p.sweep_conf_bars)
    conf_s = advance(sw.s, False, s.n_bars, bar.close, p.sweep_conf_bars)
    atr_ok = f.atr == f.atr
    if (
        sweep_d
        and sw.d.bar is None
        and atr_ok
        and far_from_all(sw.d.done, loc.tap_demand_c, f.atr * 0.7)
    ):
        sw.d.c, sw.d.edge, sw.d.x, sw.d.bar = (
            loc.tap_demand_c,
            loc.tap_demand_bot,
            bar.high,
            s.n_bars,
        )
    if (
        sweep_s
        and sw.s.bar is None
        and atr_ok
        and far_from_all(sw.s.done, loc.tap_supply_c, f.atr * 0.7)
    ):
        sw.s.c, sw.s.edge, sw.s.x, sw.s.bar = (
            loc.tap_supply_c,
            loc.tap_supply_top,
            bar.low,
            s.n_bars,
        )
    mark_d = conf_d if p.sweep_conf_only else sweep_d
    mark_s = conf_s if p.sweep_conf_only else sweep_s
    f.out.plots.update(sweep_d_conf=float(conf_d), sweep_s_conf=float(conf_s))
    gate = p.show_footprint and p.fp_mark_traps
    start = bar.bar_start_utc.isoformat()
    if gate and mark_d:
        c = centre_d if conf_d else loc.tap_demand_c
        f.out.overlay_ops.append(
            OverlayElement(
                id=f"swd:{start}",
                kind="marker",
                t0=bar.bar_start_utc,
                p0=bar.low,
                style={"role": "demand", "shape": "xcross", "pos": "below"},
            )
        )  # noqa: E501
        f.out.events.append(
            Ev(
                "alert",
                {
                    "kind": "sweep_demand",
                    "name": "Demand Sweep (bar close)",
                    "zone_center": c,
                    "imb": fp.imb,
                },
                "close",
            )
        )  # noqa: E501
    if gate and mark_s:
        c = centre_s if conf_s else loc.tap_supply_c
        f.out.overlay_ops.append(
            OverlayElement(
                id=f"sws:{start}",
                kind="marker",
                t0=bar.bar_start_utc,
                p0=bar.high,
                style={"role": "supply", "shape": "xcross", "pos": "above"},
            )
        )  # noqa: E501
        f.out.events.append(
            Ev(
                "alert",
                {
                    "kind": "sweep_supply",
                    "name": "Supply Sweep (bar close)",
                    "zone_center": c,
                    "imb": fp.imb,
                },
                "close",
            )
        )  # noqa: E501
