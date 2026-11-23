"""Step 1 (L175-209): session flags, ATR, prior day, session anchors, opening range."""

import math
from typing import Any

from nifty.engines.balu.params import BaluParams, session_minutes
from nifty.engines.balu.state import SessionState
from nifty.engines.balu.steps import BarFrame, register_slot, step
from nifty.engines.pinekit import Atr, bar_minutes_ist


class Core:
    """SessionState plus the continuous ATR(14) (`ta.atr`, NOT the session-reset ATR of NVS)."""

    def __init__(self, p: BaluParams) -> None:
        self.s = SessionState()
        self.atr = Atr(14)

    def state(self) -> dict[str, Any]:
        return {"s": self.s.state(), "atr": self.atr.state()}

    def load(self, st: dict[str, Any]) -> None:
        self.s.load(st["s"])
        self.atr.load(st["atr"])


@register_slot("core")
def make_core(p: BaluParams) -> Core:
    return Core(p)


def or_bars(p: BaluParams, tf_min: float) -> int:
    return max(1, math.ceil(p.or_minutes / tf_min))


@step(1)
def session_anchors(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    c: Core = eng.slots["core"]
    s = c.s
    bar = f.bar
    s.n_bars += 1
    f.atr = c.atr.update(bar.high, bar.low, bar.close)
    lo, hi = session_minutes(p.session_str)
    start = bar_minutes_ist(bar.bar_start_utc)
    f.in_session = lo <= start < hi
    day = eng.ctx.calendar.session_date(bar.bar_start_utc).isoformat()
    new_day = s.prev_day is None or day != s.prev_day  # timeframe.change("D")
    f.new_session = f.in_session and (not s.prev_in_session or new_day)
    s.prev_in_session, s.prev_day = f.in_session, day

    pd = eng.ctx.prior_day(bar)  # previous COMPLETED session; None on the first session
    if pd is not None:
        f.pd_h, f.pd_l, f.pd_c = pd.high, pd.low, pd.close
        f.pp = (pd.high + pd.low + pd.close) / 3.0
        f.r1, f.s1 = 2 * f.pp - pd.low, 2 * f.pp - pd.high

    ob = or_bars(p, eng.tf_min)
    if f.new_session:
        s.or_high = s.sess_hi = bar.high
        s.or_low = s.sess_lo = bar.low
        s.day_len = 1
    elif f.in_session:
        s.day_len += 1
        s.sess_hi = max(bar.high if s.sess_hi != s.sess_hi else s.sess_hi, bar.high)
        s.sess_lo = min(bar.low if s.sess_lo != s.sess_lo else s.sess_lo, bar.low)
        if s.day_len <= ob:
            s.or_high = max(bar.high if s.or_high != s.or_high else s.or_high, bar.high)
            s.or_low = min(bar.low if s.or_low != s.or_low else s.or_low, bar.low)
    f.out.plots.update(atr=f.atr, day_len=float(s.day_len), or_high=s.or_high, or_low=s.or_low)
