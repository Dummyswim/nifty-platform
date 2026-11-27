"""Pure volatility maths for the context panel. Vol is in vol points (14.2 = 14.2 %)."""

import math
from collections.abc import Sequence
from statistics import stdev
from typing import Literal

from nifty.context.params import ContextParams

Verdict = Literal["FAIR", "CHEAP", "RICH"]

_VIX_WINDOW = 252
_VIX_MIN = 200
_MINUTES_PER_SESSION = 375
_SESSIONS_PER_YEAR = 252


def vix_rank(prior_closes: Sequence[float], vix: float) -> float | None:
    """Percent of the last 252 prior closes that are <= vix; None below 200 closes."""
    if len(prior_closes) < _VIX_MIN:
        return None
    window = prior_closes[-_VIX_WINDOW:]
    return 100.0 * sum(1 for c in window if c <= vix) / len(window)


def band(vix: float, pct: float, floor: float) -> float:
    return max(pct / 100.0 * vix, floor)


def verdict(iv: float, vix: float, prev: Verdict | None, p: ContextParams) -> Verdict:
    """Classify IV against VIX. FAIR is sticky: it only ends outside the wider exit band."""
    if prev == "FAIR":
        exit_band = band(vix, p.exit_pct, p.band_floor * p.exit_pct / p.band_pct)
        if abs(iv - vix) <= exit_band:
            return "FAIR"
    entry = band(vix, p.band_pct, p.band_floor)
    if iv - vix > entry:
        return "RICH"
    if vix - iv > entry:
        return "CHEAP"
    return "FAIR"


def interp_iv(spot: float, lo: tuple[float, float], hi: tuple[float, float]) -> float:
    """Linear interpolation in strike between (strike, iv) pairs."""
    (k0, v0), (k1, v1) = lo, hi
    if k0 == k1:
        return v0
    return v0 + (v1 - v0) * (spot - k0) / (k1 - k0)


def realised_vol(closes_1m_by_session: Sequence[Sequence[float]]) -> float | None:
    """Annualised vol points from 1m log returns pooled within sessions (no overnight)."""
    if len(closes_1m_by_session) < 2:
        return None
    rets = [
        math.log(b / a)
        for closes in closes_1m_by_session
        for a, b in zip(closes, closes[1:], strict=False)
    ]
    if len(rets) < 2:
        return None
    return stdev(rets) * math.sqrt(_MINUTES_PER_SESSION * _SESSIONS_PER_YEAR) * 100.0


def fair_straddle_prem(spot: float, vix: float, t_years: float) -> float:
    return 0.8 * spot * vix / 100.0 * math.sqrt(t_years)


def expected_move_pts(prev_close: float, vix_open: float) -> float:
    return prev_close * vix_open / 100.0 / math.sqrt(_SESSIONS_PER_YEAR)
