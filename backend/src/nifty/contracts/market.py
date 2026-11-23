from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Timeframe = Literal["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"]
# 1d is one bar per session (length comes from the Calendar), so it is not listed here.
TF_MINUTES: dict[str, int] = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60}
VolumeKind = Literal["exchange", "absent", "synthetic", "proxy"]
QUALITY_FLAGS = frozenset(
    {
        "off_grid",
        "gap_before",
        "stale",
        "zero_range",
        "partial_bucket",
        "volume_absent",
        "calendar_unverified",
        "reconciled",
    }
)


class Instrument(BaseModel, frozen=True):
    instrument_id: str
    provider: Literal["kite", "csv"]
    provider_token: int | None = None
    exchange: str | None = None
    segment: str | None = None
    instrument_type: Literal["INDEX", "EQ", "FUT", "CE", "PE"] = "INDEX"
    tradingsymbol: str
    underlying: str | None = None
    expiry: date | None = None
    strike: float | None = None
    option_type: Literal["CE", "PE"] | None = None
    tick_size: float | None = None
    lot_size: int | None = None
    currency: str = "INR"
    metadata_version: str | None = None
    provider_meta: dict[str, Any] = Field(default_factory=dict)


class Bar(BaseModel, frozen=True):
    instrument_id: str
    provider: str
    timeframe: Timeframe
    bar_start_utc: datetime
    bar_end_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    volume_kind: VolumeKind = "exchange"
    finalized: bool = True
    received_at_utc: datetime
    revision: int = 0
    quality_flags: tuple[str, ...] = ()


class Exclusion(BaseModel):
    ts: datetime
    reason: str


class Gap(BaseModel):
    day: date
    from_ts: datetime  # first missing bar start
    to_ts: datetime  # last missing bar start
    missing: int


class SessionInfo(BaseModel):
    date: date
    first: datetime
    last: datetime
    n: int


class ValidationReport(BaseModel):
    rows_in: int
    rows_ok: int
    excluded: list[Exclusion] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    duplicates: int = 0
    out_of_order: int = 0
    sessions: list[SessionInfo] = Field(default_factory=list)
    volume_kind: VolumeKind = "exchange"
    calendar_unverified: bool = True
