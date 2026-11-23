"""Step 11 (L664-700): intrabar pressure from the 1m sub-bars, plus the EARLY (provisional) version.
Index data has no volume, so effort is the sub-bar range."""

import copy
import math
from dataclasses import dataclass
from typing import Any

from nifty.contracts import Bar, EngineOutput, Ev, OverlayElement, PlotSpec
from nifty.engines.balu.location import locate
from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.steps import PLOT_SPECS, BarFrame, provisional, register_slot, step
from nifty.engines.context import ConfigError
from nifty.engines.pinekit import NaN, Sma, nz

PLOT_SPECS += [
    PlotSpec(name=n, pane="own")
    for n in ("fp_n", "fp_tot", "fp_imb", "fp_valid", "press_buy", "press_sell")
]
RES = {1: "1m", 3: "3m", 5: "5m", 10: "10m", 15: "15m", 30: "30m", 60: "1h"}


class PressureState:
    def __init__(self, p: BaluParams) -> None:
        self.avg = Sma(p.fp_eff_len)  # over chart bars of the WHOLE history

    def state(self) -> dict[str, Any]:
        return {"avg": self.avg.state()}

    def load(self, st: dict[str, Any]) -> None:
        self.avg.load(st["avg"])


@register_slot("pressure")
def make_pressure(p: BaluParams) -> PressureState:
    return PressureState(p)


@dataclass
class Reading:
    n: int = 0
    tot: float = 0.0
    net: float = 0.0
    imb: float = 0.0
    valid: bool = False
    big: bool = False
    press_buy: bool = False
    press_sell: bool = False


def sub_resolution(p: BaluParams, tf_min: float) -> str | None:
    """None = suppressed (fpLtf not below the chart); ConfigError if it cannot divide it."""
    if not p.fp_ltf.isdigit() or int(p.fp_ltf) not in RES:
        raise ConfigError(f"fp_ltf {p.fp_ltf!r} must be one of {sorted(RES)} (minutes)")
    ltf = int(p.fp_ltf)
    if ltf >= tf_min:
        return None
    if tf_min % ltf:
        raise ConfigError(f"fp_ltf {ltf}m does not divide the chart timeframe ({tf_min:g}m)")
    return RES[ltf]


def sums(subs: list[Bar]) -> tuple[int, float, float]:
    tot = net = 0.0
    for b in subs:
        rng = b.high - b.low
        effort = b.volume if b.volume > 0 else rng
        signed = ((2 * b.close - b.high - b.low) / rng if rng > 0 else 0.0) * effort
        tot, net = tot + nz(effort), net + nz(signed)
    return len(subs), tot, net


def read(
    subs: list[Bar] | None, avg: float, p: BaluParams, at_demand: bool, at_supply: bool
) -> Reading:  # fmt: skip
    r = Reading()
    if subs:
        r.n, r.tot, r.net = sums(subs)
    r.valid = p.show_footprint and subs is not None and r.n >= p.fp_min_sub_bars and r.tot > 0
    r.imb = r.net / r.tot if r.tot > 0 else 0.0
    r.big = r.valid and (avg != avg or r.tot >= avg * p.fp_eff_mult)
    r.press_buy = r.big and r.imb >= p.fp_imbal and (not p.fp_at_zone_only or at_demand)
    r.press_sell = r.big and r.imb <= -p.fp_imbal and (not p.fp_at_zone_only or at_supply)
    return r


def _marker(
    f: BarFrame, kind: str, role: str, price: float, pos: str, shape: str
) -> OverlayElement:
    return OverlayElement(
        id=f"{kind}:{f.bar.bar_start_utc.isoformat()}", kind="marker", t0=f.bar.bar_start_utc,
        p0=price, style={"role": role, "shape": shape, "pos": pos},
    )  # fmt: skip


@step(11)
def pressure(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    st: PressureState = eng.slots["pressure"]
    loc = f.extra["location"]
    res = sub_resolution(p, eng.tf_min)
    subs = eng.ctx.sub_bars(f.bar, res) if res is not None else None
    n_tot = sums(subs)[1] if subs else 0.0
    avg = st.avg.update(n_tot)  # fpTot is 0 when no sub-bars; the average runs on every chart bar
    r = read(subs, avg, p, loc.at_demand, loc.at_supply)
    f.extra["fp"] = r
    f.out.plots.update(
        fp_n=float(r.n), fp_tot=r.tot, fp_imb=r.imb, fp_valid=float(r.valid),
        press_buy=float(r.press_buy), press_sell=float(r.press_sell),
    )  # fmt: skip
    if r.press_buy:
        f.out.overlay_ops.append(_marker(f, "pb", "demand", f.bar.low, "below", "circle"))
        f.out.events.append(
            Ev("alert", {"kind": "press_buy", "name": "Buy Pressure (bar close)",
                         "zone_center": loc.tap_demand_c, "imb": r.imb}, "close")
        )  # fmt: skip
    if r.press_sell:
        f.out.overlay_ops.append(_marker(f, "ps", "supply", f.bar.high, "above", "circle"))
        f.out.events.append(
            Ev("alert", {"kind": "press_sell", "name": "Sell Pressure (bar close)",
                         "zone_center": loc.tap_supply_c, "imb": r.imb}, "close")
        )  # fmt: skip


@provisional
def pressure_early(eng: Any, bar: Bar) -> EngineOutput:
    """EARLY pressure on the partial sub-bars against the LAST CONFIRMED zones (may cancel at the
    close). Reads state, never writes it: the SMA is a copy, zones/sweeps/path are untouched."""
    out = EngineOutput()
    p: BaluParams = eng.p
    book = eng.slots["zones"]
    if not (book.last_atr == book.last_atr and book.last_atr > 0):
        return out
    res = sub_resolution(p, eng.tf_min)
    if res is None:
        return out
    subs = eng.ctx.sub_bars(bar, res)
    avg_win = copy.deepcopy(eng.slots["pressure"].avg)
    avg = avg_win.update(sums(subs)[1] if subs else 0.0)
    loc = locate(book.zones, bar.close, book.last_atr, p.zone_prox_atr)
    r = read(subs, avg, p, loc.at_demand, loc.at_supply)
    for hit, kind, center in ((r.press_buy, "press_buy_early", loc.tap_demand_c),
                              (r.press_sell, "press_sell_early", loc.tap_supply_c)):  # fmt: skip
        if hit:
            name = (
                "EARLY Buy Pressure (may cancel)"
                if "buy" in kind
                else "EARLY Sell Pressure (may cancel)"
            )
            out.events.append(
                Ev(
                    "alert",
                    {"kind": kind, "name": name, "zone_center": center, "imb": r.imb},
                    "close",
                )
            )
    _ = (math, NaN)
    return out
