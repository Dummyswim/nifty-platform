"""Time helpers: UTC internally, Asia/Kolkata at the edges (D21)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)
