"""Strike step, ATM, strike types and expiry kinds, all derived from the listed contracts (D10)."""

from collections import Counter
from collections.abc import Sequence
from datetime import date

STRIKE_TYPES = ("Deep ITM", "ITM", "ATM", "OTM", "Deep OTM")
# Offsets in strike STEPS. Defaults are ours (documented in STATE), editable in prefs.
DEFAULT_OFFSETS: dict[str, int] = {"Deep ITM": 5, "ITM": 2, "ATM": 0, "OTM": 2, "Deep OTM": 5}
EXPIRY_KINDS = ("current weekly", "next weekly", "monthly")


def strike_step(strikes: Sequence[float]) -> float | None:
    """Modal gap between listed strikes (ties: the smaller gap); None below 2 strikes."""
    ks = sorted(set(strikes))
    gaps = Counter(round(b - a, 6) for a, b in zip(ks, ks[1:], strict=False))
    if not gaps:
        return None
    best = max(gaps.values())
    return min(g for g, n in gaps.items() if n == best)


def atm(spot: float, strikes: Sequence[float]) -> float | None:
    """Nearest listed strike; an exact tie goes to the LOWER strike."""
    ks = sorted(set(strikes))
    if not ks:
        return None
    return min(ks, key=lambda k: (abs(k - spot), k))


def strike_for(
    strike_type: str, option_type: str, atm_strike: float, step: float, listed: Sequence[float],
    offsets: dict[str, int] | None = None,
) -> float | None:  # fmt: skip
    """CE: ITM = lower strikes, OTM = higher; PE mirrored. None when that strike is not listed."""
    n = (offsets or DEFAULT_OFFSETS)[strike_type]
    if strike_type == "ATM":
        sign = 0
    elif strike_type in ("ITM", "Deep ITM"):
        sign = -1 if option_type == "CE" else 1
    else:
        sign = 1 if option_type == "CE" else -1
    target = round(atm_strike + sign * n * step, 6)
    return next((k for k in listed if abs(k - target) < 1e-6), None)


def expiry_kinds(expiries: Sequence[date], today: date) -> dict[str, date | None]:
    """Current weekly = the nearest listed expiry on/after today, next weekly = the one after it,
    monthly = the last listed expiry of a calendar month (the first such on/after today). A kind the
    master does not list is None ("unavailable"), never guessed."""
    live = sorted({e for e in expiries if e >= today})
    last_of_month: dict[tuple[int, int], date] = {}
    for e in live:
        last_of_month[(e.year, e.month)] = e  # sorted ascending: the last write wins
    monthly = min(last_of_month.values(), default=None)
    return {
        "current weekly": live[0] if live else None,
        "next weekly": live[1] if len(live) > 1 else None,
        "monthly": monthly,
    }
