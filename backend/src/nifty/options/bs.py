"""Black-Scholes (european, q = 0). Greeks are `computed`, never exchange data (D11).

Conventions: T in years (calendar, 365 d) to 15:30 IST of the expiry; theta is per calendar day;
vega is per 1 volatility point (0.01); rates and vols are decimals."""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from nifty.timeutil import IST

LABEL = "computed (Black-Scholes, q=0)"
YEAR_S = 365 * 86400


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    theta_day: float
    vega_1pct: float


def years_to_expiry(expiry: date, now: datetime) -> float:
    end = datetime.combine(expiry, time(15, 30), tzinfo=IST)
    return max(0.0, (end - now).total_seconds() / YEAR_S)


def bs(s: float, k: float, t: float, r: float, sigma: float, is_call: bool) -> Greeks | None:
    """None when the inputs cannot define a price (t <= 0, sigma <= 0, non-positive s or k)."""
    if t <= 0 or sigma <= 0 or s <= 0 or k <= 0:
        return None
    sq = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / sq
    d2 = d1 - sq
    disc = math.exp(-r * t)
    if is_call:
        price = s * _cdf(d1) - k * disc * _cdf(d2)
        delta = _cdf(d1)
        theta = -s * _pdf(d1) * sigma / (2 * math.sqrt(t)) - r * k * disc * _cdf(d2)
    else:
        price = k * disc * _cdf(-d2) - s * _cdf(-d1)
        delta = _cdf(d1) - 1.0
        theta = -s * _pdf(d1) * sigma / (2 * math.sqrt(t)) + r * k * disc * _cdf(-d2)
    gamma = _pdf(d1) / (s * sq)
    vega = s * _pdf(d1) * math.sqrt(t)
    return Greeks(price, delta, gamma, theta / 365.0, vega * 0.01)


def implied_vol(
    price: float, s: float, k: float, t: float, r: float, is_call: bool,
    lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-7,
) -> float | None:  # fmt: skip
    """Bisection on sigma. None when the price is outside the no-arbitrage band for [lo, hi]."""
    if t <= 0 or price <= 0 or s <= 0 or k <= 0:
        return None
    a, b = bs(s, k, t, r, lo, is_call), bs(s, k, t, r, hi, is_call)
    if a is None or b is None or not (a.price <= price <= b.price):
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        g = bs(s, k, t, r, mid, is_call)
        assert g is not None
        if abs(g.price - price) < tol or hi - lo < 1e-10:
            return mid
        if g.price < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def effective_today(now: datetime) -> date:
    """The trading day an option decision belongs to: after 15:30 IST the next calendar day."""
    local = now.astimezone(IST)
    d = local.date()
    return d + timedelta(days=1) if local.time() >= time(15, 30) else d
