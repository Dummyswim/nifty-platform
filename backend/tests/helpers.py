import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from nifty.contracts import Bar
from nifty.timeutil import Calendar

CAL = Calendar()
ORACLE = Path(__file__).resolve().parents[2] / "reference" / "oracle" / "data" / "nifty_1m.csv"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def bar(
    start: datetime,
    o: float = 100.0,
    h: float = 101.0,
    lo: float = 99.0,
    c: float = 100.5,
    v: float = 10.0,
    tf: str = "1m",
    **kw: object,
) -> Bar:
    mins = {"1m": 1, "5m": 5}.get(tf, 1)
    return Bar(
        instrument_id="csv:T",
        provider="csv",
        timeframe=tf,  # type: ignore[arg-type]
        bar_start_utc=start,
        bar_end_utc=start + timedelta(minutes=mins),
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=v,
        received_at_utc=NOW,
        **kw,  # type: ignore[arg-type]
    )


def day_bars(
    d: date, first_min: int = 0, last_min: int = 374, skip: frozenset[int] = frozenset()
) -> list[Bar]:
    """1m bars of session day d for minute offsets first_min..last_min from 09:15 IST."""
    open_, _ = CAL.session_bounds(d)
    out = []
    for i in range(first_min, last_min + 1):
        if i in skip:
            continue
        p = 100.0 + i
        out.append(bar(open_ + timedelta(minutes=i), p, p + 2, p - 2, p + 1, 5.0 + i))
    return out


def wave(d: date, n: int = 375, period: int = 23) -> list[Bar]:
    """1m bars whose close oscillates so moving averages cross both ways."""
    open_, _ = CAL.session_bounds(d)
    out = []
    for i in range(n):
        c = 25000 + 20 * math.sin(2 * math.pi * i / period)
        out.append(bar(open_ + timedelta(minutes=i), c, c + 1, c - 1, c, 5.0))
    return out
