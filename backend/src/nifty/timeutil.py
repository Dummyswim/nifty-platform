"""Time helpers: UTC inside, Asia/Kolkata at the edges (D21), and the session Calendar (D09)."""

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
# repo root /data/calendar.yml regardless of cwd (backend/src/nifty/timeutil.py -> parents[3])
DEFAULT_CALENDAR_PATH = Path(__file__).resolve().parents[3] / "data" / "calendar.yml"


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


class Calendar:
    """Weekdays only unless the user lists holidays/special sessions in data/calendar.yml.

    Dates after `verified_through` (or any date when it is absent) are `calendar_unverified`.
    Holidays are never guessed.
    """

    def __init__(
        self,
        holidays: frozenset[date] = frozenset(),
        special: dict[date, tuple[time, time]] | None = None,
        verified_through: date | None = None,
    ) -> None:
        self.holidays = holidays
        self.special = special or {}
        self.verified_through = verified_through

    @classmethod
    def load(cls, path: Path | None = None) -> "Calendar":
        p = path or DEFAULT_CALENDAR_PATH
        if not p.exists():
            return cls()
        raw = yaml.safe_load(p.read_text()) or {}
        vt = raw.get("verified_through")
        return cls(
            holidays=frozenset(date.fromisoformat(str(d)) for d in raw.get("holidays") or []),
            special={
                date.fromisoformat(str(s["date"])): (_hhmm(str(s["open"])), _hhmm(str(s["close"])))
                for s in raw.get("special_sessions") or []
            },
            verified_through=date.fromisoformat(str(vt)) if vt else None,
        )

    def is_session_day(self, d: date) -> bool:
        if d in self.holidays:
            return False
        return d in self.special or d.weekday() < 5

    def is_verified(self, d: date) -> bool:
        return self.verified_through is not None and d <= self.verified_through

    def session_bounds(self, d: date) -> tuple[datetime, datetime]:
        """(open, close) in UTC; close is exclusive."""
        o, c = self.special.get(d, (SESSION_OPEN, SESSION_CLOSE))
        return (
            datetime.combine(d, o, tzinfo=IST).astimezone(UTC),
            datetime.combine(d, c, tzinfo=IST).astimezone(UTC),
        )

    @staticmethod
    def session_date(ts: datetime) -> date:
        return ts.astimezone(IST).date()


ONE_MINUTE = timedelta(minutes=1)
