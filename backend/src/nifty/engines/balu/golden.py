"""Step 4 (L308-357): Golden Line (session VWAP, TWAP, pivot or EMA) and the regime hysteresis."""

from typing import Any

from nifty.contracts import PlotSpec
from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.steps import PLOT_SPECS, BarFrame, register_slot, step
from nifty.engines.pinekit import Ema, NaN, Series, nz

PLOT_SPECS += [
    PlotSpec(name="golden", role="gold", pane="overlay"),
    PlotSpec(name="gold_val", role="gold", pane="overlay"),
    PlotSpec(name="gold_state", pane="own"),
    PlotSpec(name="regime_idx", kind="step", pane="own"),
]


class GoldWindows:
    def __init__(self, p: BaluParams) -> None:
        self.ema = Ema(p.gold_ema_len, p.ema_seed)
        self.hist = Series(p.flow_slope_len)  # goldVal[1..flow_slope_len]

    def state(self) -> dict[str, Any]:
        return {"ema": self.ema.state(), "hist": self.hist.state()}

    def load(self, st: dict[str, Any]) -> None:
        self.ema.load(st["ema"])
        self.hist.load(st["hist"])


@register_slot("gold")
def make_gold(p: BaluParams) -> GoldWindows:
    return GoldWindows(p)


@step(4)
def golden(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    g: GoldWindows = eng.slots["gold"]
    s = eng.slots["core"].s
    bar = f.bar
    vol = nz(bar.volume)
    s.vol_seen = s.vol_seen or vol > 0  # sticky for the whole run, not per session
    proxy = nz(eng.ctx.proxy_volume(bar) or NaN) if p.gold_proxy else 0.0
    if f.new_session:
        s.g_chart_pv = s.g_chart_w = s.g_proxy_pv = s.g_proxy_w = s.g_sum_p = 0.0
        s.g_cnt = 0
    hlc3 = (bar.high + bar.low + bar.close) / 3.0
    if f.in_session:
        s.g_chart_pv += hlc3 * vol
        s.g_chart_w += vol
        s.g_proxy_pv += hlc3 * proxy
        s.g_proxy_w += proxy
        s.g_sum_p += hlc3
        s.g_cnt += 1
    # the branch can switch mid-session when volume first appears: replicated on purpose
    if s.g_chart_w > 0:
        vwap, anchor = s.g_chart_pv / s.g_chart_w, "VWAP"
    elif p.gold_proxy and s.g_proxy_w > 0:
        vwap, anchor = s.g_proxy_pv / s.g_proxy_w, "Proxy weighted"
    elif s.g_cnt > 0:
        vwap = s.g_sum_p / s.g_cnt
        anchor = "Proxy unavailable: TWAP" if p.gold_proxy else "TWAP (no vol)"
    else:
        vwap, anchor = NaN, "TWAP (no vol)"
    if p.gold_source == "Daily Pivot (PP)":
        val, f.gold_anchor = f.pp, "Daily PP"
    elif p.gold_source == "EMA":
        val, f.gold_anchor = g.ema.update(bar.close), "EMA"
    else:
        val, f.gold_anchor = vwap, anchor
    f.gold_val = val

    dead = f.atr * p.gold_dead_atr
    if f.new_session:
        s.gold_state = 0
    if bar.close > val + dead:  # NaN compares false: the previous direction is retained
        s.gold_state = 1
    elif bar.close < val - dead:
        s.gold_state = -1
    f.gold_state = s.gold_state

    slope = val - g.hist[p.flow_slope_len - 1] if s.day_len > p.flow_slope_len else 0.0
    if s.gold_state > 0:
        s.regime_idx = 2 if slope >= 0 else 1
    elif s.gold_state < 0:
        s.regime_idx = 0 if slope <= 0 else 1
    else:
        s.regime_idx = 1
    f.regime_idx = s.regime_idx
    g.hist.push(val)
    f.out.plots.update(
        golden=NaN if f.new_session else val,  # break the line at each session open (L357)
        gold_val=val,
        gold_state=float(s.gold_state),
        regime_idx=float(s.regime_idx),
    )
