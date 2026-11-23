"""Steps 5 and 6 (L360-430): the Moving Line (session cumulative delta), flow state, divergence."""

from datetime import UTC, datetime
from typing import Any

from nifty.contracts import Ev, PlotSpec
from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.steps import PLOT_SPECS, BarFrame, register_slot, step
from nifty.engines.pinekit import Ema, NaN, PivotHigh, PivotLow, Series, Stdev, Sum

PLOT_SPECS += [
    PlotSpec(name="cvd", pane="own"),
    PlotSpec(name="moving_line", kind="step", role="neutral", pane="overlay"),
    PlotSpec(name="moving_line_raw", pane="overlay"),
    PlotSpec(name="flow_z", pane="own"),
    PlotSpec(name="flow_state", kind="step", pane="own"),
    PlotSpec(name="flow_ready", pane="own"),
    PlotSpec(name="day_len", pane="own"),
    PlotSpec(name="or_high", role="warn", pane="overlay"),
    PlotSpec(name="or_low", role="warn", pane="overlay"),
    PlotSpec(name="atr", pane="own"),
    PlotSpec(name="pool_size", pane="own"),
]


class FlowWindows:
    def __init__(self, p: BaluParams) -> None:
        self.ema = Ema(p.flow_smooth_len, p.ema_seed)  # continuous across sessions
        self.sum = Sum(p.flow_slope_len)
        self.sd = Stdev(100)  # population (biased), NaN until the window is full
        self.ph = PivotHigh(p.div_pivot_len, p.div_pivot_len, p.pivot_ties)
        self.pl = PivotLow(p.div_pivot_len, p.div_pivot_len, p.pivot_ties)
        self.cvd_hist = Series(p.div_pivot_len)  # cvd[1..L]
        self.starts = Series(p.div_pivot_len)  # bar start epoch seconds [1..L]

    def state(self) -> dict[str, Any]:
        return {
            k: getattr(self, k).state()
            for k in ("ema", "sum", "sd", "ph", "pl", "cvd_hist", "starts")
        }

    def load(self, st: dict[str, Any]) -> None:
        for k in ("ema", "sum", "sd", "ph", "pl", "cvd_hist", "starts"):
            getattr(self, k).load(st[k])


@register_slot("flow")
def make_flow(p: BaluParams) -> FlowWindows:
    return FlowWindows(p)


@step(5)
def moving_line(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    w: FlowWindows = eng.slots["flow"]
    s = eng.slots["core"].s
    bar = f.bar
    mintick = eng.ctx.mintick
    range_bar = max(bar.high - bar.low, mintick)
    use_real = p.cvd_source == "Real Volume" or (p.cvd_source == "Auto" and s.vol_seen)
    close_pos = (bar.close - bar.low) / range_bar
    delta_size = bar.volume if use_real else range_bar
    bar_delta = delta_size * (2 * close_pos - 1)
    if f.in_session:
        s.cvd = bar_delta if f.new_session else s.cvd + bar_delta
    if f.new_session or s.cvd_hi != s.cvd_hi:
        s.cvd_hi = s.cvd_lo = s.cvd
    else:
        s.cvd_hi, s.cvd_lo = max(s.cvd_hi, s.cvd), min(s.cvd_lo, s.cvd)
    f.cvd = s.cvd
    sess_hi = bar.high if s.sess_hi != s.sess_hi else s.sess_hi
    sess_lo = bar.low if s.sess_lo != s.sess_lo else s.sess_lo
    price_span = max(sess_hi - sess_lo, mintick)
    s.flow_ready = f.flow_ready = s.day_len >= p.flow_warm_bars and (s.cvd_hi - s.cvd_lo) > 0
    line = sess_lo + (s.cvd - s.cvd_lo) / max(s.cvd_hi - s.cvd_lo, 1e-9) * price_span

    slope = w.sum.update(w.ema.update(bar_delta))
    sd = w.sd.update(slope)
    s.flow_z = slope / sd if sd > 0 else 0.0  # NaN sd (warm-up) => 0, not NaN
    s.flow_state = 1 if s.flow_z > p.flow_dead else -1 if s.flow_z < -p.flow_dead else 0
    f.flow_state = s.flow_state
    f.out.plots.update(
        cvd=s.cvd,
        moving_line=line if f.flow_ready else NaN,
        moving_line_raw=line,
        flow_z=s.flow_z,
        flow_state=float(s.flow_state),
        flow_ready=1.0 if f.flow_ready else 0.0,
    )


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


@step(6)
def divergence(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    w: FlowWindows = eng.slots["flow"]
    s = eng.slots["core"].s
    bar = f.bar
    ph, pl = w.ph.update(bar.high), w.pl.update(bar.low)
    if f.new_session:
        s.last_ph = s.last_ph_cvd = s.last_pl = s.last_pl_cvd = NaN
    n = p.div_pivot_len
    cvd_then = w.cvd_hist[n - 1]  # raw cvd at the pivot bar (L bars back)
    pivot_start = w.starts[n - 1]
    ready = p.show_div and s.day_len > 2 * n
    known = bar.bar_start_utc.isoformat()
    if ready and ph == ph:
        if s.last_ph == s.last_ph and ph > s.last_ph and cvd_then < s.last_ph_cvd:
            f.bear_div = True
            f.out.events.append(
                Ev(
                    "divergence",
                    {
                        "side": "bear",
                        "pivot_bar_start": _iso(pivot_start),
                        "known_bar_start": known,
                    },
                    "close",
                )
            )
        s.last_ph, s.last_ph_cvd = ph, cvd_then
    if ready and pl == pl:
        if s.last_pl == s.last_pl and pl < s.last_pl and cvd_then > s.last_pl_cvd:
            f.bull_div = True
            f.out.events.append(
                Ev(
                    "divergence",
                    {
                        "side": "bull",
                        "pivot_bar_start": _iso(pivot_start),
                        "known_bar_start": known,
                    },
                    "close",
                )
            )
        s.last_pl, s.last_pl_cvd = pl, cvd_then
    w.cvd_hist.push(s.cvd)
    w.starts.push(bar.bar_start_utc.timestamp())
