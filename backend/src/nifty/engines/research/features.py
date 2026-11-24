"""Causal features on finalized bars (spec/07, research prompt §6).

P close, F EMA fast, S EMA slow, V session anchor, A = the PRIOR completed bar's session-adjusted ATR
(valid and > 0, else NaN: never an infinity). D=(P-V)/A, E=(P-F)/A, M=(F-S)/A. Rates over k completed
bars of the SAME session (never bridging the anchor reset): ATR per bar, not points per second.
`atr_sess` is the session-adjusted Wilder ATR (first bar TR = high - low), distinct from the standard
ATR and from Balu's. EMAs are warmed from all earlier bars the run supplies (no future data)."""

import math
from dataclasses import dataclass
from typing import Any

from nifty.contracts import Bar
from nifty.engines.pinekit import AtrSess, Ema, NaN, dec, enc, nz
from nifty.engines.research.params import ResearchParams
from nifty.timeutil import Calendar

ANCHOR_VWAP = "VWAP"
ANCHOR_PROXY = "proxy weighted"
ANCHOR_TWAP = "TWAP / equal-bar session average"


@dataclass
class Features:
    p: float
    f: float
    s: float
    v: float
    a: float
    d: float
    e: float
    m: float
    price_to_slow: float
    fast_to_anchor: float
    slow_to_anchor: float
    anchor_rate: float
    gap_rate: float
    prev_gap_rate: float
    prev_p: float
    prev_v: float
    anchor_kind: str
    new_session: bool
    sign: int  # +1 bull context (F > S), -1 bear, 0 none


def _div(x: float, a: float) -> float:
    return x / a if a == a and a > 0 and x == x else NaN


class FeatureState:
    def __init__(self, p: ResearchParams) -> None:
        self.p = p
        self.ema_f, self.ema_s = Ema(p.ema_fast, p.ema_seed), Ema(p.ema_slow, p.ema_seed)
        self.atr = AtrSess(p.atr_len)
        self.prev_atr = NaN
        self.day: str | None = None
        self.sum_pv = self.sum_w = self.sum_pw = self.sum_ppv = self.sum_p = 0.0
        self.cnt = 0
        self.pv_hist: list[float] = []  # (P - V) per bar of the current session
        self.gap_hist: list[float] = []  # (F - S) per bar of the current session
        self.prev_p = self.prev_v = self.prev_gap_rate = NaN

    def update(self, bar: Bar, cal: Calendar, proxy_vol: float | None = None) -> Features:
        p = self.p
        day = cal.session_date(bar.bar_start_utc).isoformat()
        new = day != self.day
        if new:
            self.day, self.cnt = day, 0
            self.sum_pv = self.sum_w = self.sum_pw = self.sum_ppv = self.sum_p = 0.0
            self.pv_hist, self.gap_hist = [], []
        a = self.prev_atr if self.prev_atr == self.prev_atr and self.prev_atr > 0 else NaN
        atr_now = self.atr.update(bar.high, bar.low, bar.close, new)
        self.prev_atr = atr_now
        f, s = self.ema_f.update(bar.close), self.ema_s.update(bar.close)
        hlc3 = (bar.high + bar.low + bar.close) / 3.0
        vol = 0.0 if bar.volume_kind == "absent" else nz(bar.volume)
        pv = nz(proxy_vol) if (p.anchor_proxy and proxy_vol is not None) else 0.0
        self.sum_pv, self.sum_w = self.sum_pv + hlc3 * vol, self.sum_w + vol
        self.sum_ppv, self.sum_pw = self.sum_ppv + hlc3 * pv, self.sum_pw + pv
        self.sum_p, self.cnt = self.sum_p + hlc3, self.cnt + 1
        if self.sum_w > 0:
            v, kind = self.sum_pv / self.sum_w, ANCHOR_VWAP
        elif self.sum_pw > 0:
            v, kind = self.sum_ppv / self.sum_pw, ANCHOR_PROXY
        else:
            v, kind = self.sum_p / self.cnt, ANCHOR_TWAP
        P = bar.close
        self.pv_hist.append(P - v)
        self.gap_hist.append(f - s if f == f and s == s else NaN)
        k = p.rate_k
        anchor_rate = (
            _div(self.pv_hist[-1] - self.pv_hist[-1 - k], k * a)
            if len(self.pv_hist) > k and a == a
            else NaN
        )
        gap_rate = (
            _div(self.gap_hist[-1] - self.gap_hist[-1 - k], k * a)
            if len(self.gap_hist) > k and a == a
            else NaN
        )
        d, e, m = _div(P - v, a), _div(P - f, a), _div(f - s, a)
        sign = 1 if (f == f and s == s and f > s) else -1 if (f == f and s == s and f < s) else 0
        out = Features(
            P, f, s, v, a, d, e, m, e + m, d - e, d - e - m, anchor_rate, gap_rate, self.prev_gap_rate,
            self.prev_p, self.prev_v, kind, new, sign,
        )  # fmt: skip
        self.prev_p, self.prev_v, self.prev_gap_rate = P, v, gap_rate
        return out

    def state(self) -> dict[str, Any]:
        return {
            "ema_f": self.ema_f.state(), "ema_s": self.ema_s.state(), "atr": self.atr.state(),
            "prev_atr": enc([self.prev_atr])[0], "day": self.day, "sums": enc([self.sum_pv, self.sum_w, self.sum_pw, self.sum_ppv, self.sum_p]),
            "cnt": self.cnt, "pv_hist": enc(self.pv_hist), "gap_hist": enc(self.gap_hist),
            "prev": enc([self.prev_p, self.prev_v, self.prev_gap_rate]),
        }  # fmt: skip

    def load(self, st: dict[str, Any]) -> None:
        self.ema_f.load(st["ema_f"])
        self.ema_s.load(st["ema_s"])
        self.atr.load(st["atr"])
        self.prev_atr = dec([st["prev_atr"]])[0]
        self.day, self.cnt = st["day"], st["cnt"]
        self.sum_pv, self.sum_w, self.sum_pw, self.sum_ppv, self.sum_p = dec(st["sums"])
        self.pv_hist, self.gap_hist = dec(st["pv_hist"]), dec(st["gap_hist"])
        self.prev_p, self.prev_v, self.prev_gap_rate = dec(st["prev"])


_ = math
