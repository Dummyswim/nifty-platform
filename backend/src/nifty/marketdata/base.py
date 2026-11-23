"""Provider interface (D01) and error taxonomy. Adapters are read-only."""

from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from nifty.contracts import Bar, Instrument


class ErrorCode(StrEnum):
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    ENTITLEMENT = "ENTITLEMENT"
    NETWORK = "NETWORK"
    BAD_DATA = "BAD_DATA"


class ProviderError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Tick:
    instrument_id: str
    ts: datetime
    last_price: float
    volume: float | None = None
    oi: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_qty: float | None = None
    ask_qty: float | None = None
    received_at: datetime | None = None


class MarketDataProvider(Protocol):
    def list_instruments(self) -> list[Instrument]: ...

    def historical(
        self, instrument: Instrument, tf: str, start: datetime, end: datetime
    ) -> Iterable[Bar]: ...

    def stream(self, instruments: Sequence[Instrument], mode: str) -> AsyncIterator[Tick]: ...

    def status(self) -> dict[str, Any]: ...
