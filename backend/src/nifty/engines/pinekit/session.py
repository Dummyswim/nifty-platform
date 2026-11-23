"""IST time and session helpers. Causal: they only use the bar itself, the previous bar, or the
calendar (never "is the next bar a new session")."""

from datetime import datetime, timedelta

from nifty.contracts import TF_MINUTES, Bar
from nifty.timeutil import Calendar, to_ist

_MIN = timedelta(minutes=1)


def bar_minutes_ist(ts: datetime) -> int:
    """Minutes since midnight IST of an instant (use bar_start or bar_end)."""
    t = to_ist(ts)
    return t.hour * 60 + t.minute


def is_new_session(bar: Bar, prev: Bar | None, cal: Calendar) -> bool:
    return prev is None or cal.session_date(prev.bar_start_utc) != cal.session_date(
        bar.bar_start_utc
    )


def is_last_bar_of_session(bar: Bar, cal: Calendar) -> bool:
    d = cal.session_date(bar.bar_start_utc)
    return bar.bar_end_utc >= cal.session_bounds(d)[1]


def bucket_start(res: str, t: datetime, cal: Calendar) -> datetime:
    """Start of the session-anchored `res` bucket containing t (1d = session open)."""
    open_, _ = cal.session_bounds(cal.session_date(t))
    if res == "1d":
        return open_
    n = TF_MINUTES[res]
    return open_ + (int((t - open_) / _MIN) // n) * n * _MIN


def timeframe_change(bar: Bar, prev: Bar | None, res: str, cal: Calendar) -> bool:
    """Pine timeframe.change(res): the bar opens a new `res` bucket (D for res='1d')."""
    if prev is None:
        return True
    return bucket_start(res, bar.bar_start_utc, cal) != bucket_start(res, prev.bar_start_utc, cal)
