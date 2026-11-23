"""KiteProvider: historical 1m candles split by the per-request day limit, merged and deduplicated
(D08: only 1m is stored). The live stream arrives with C08."""

from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from nifty.contracts import Bar, Instrument
from nifty.marketdata.base import ErrorCode, ProviderError, Tick
from nifty.marketdata.importer import ImportRejected, parse_kite_candles
from nifty.marketdata.kite.client import KiteClient

# ASSUMED (not on the docs pages, spec/08): days per request. `kite-smoke --probe-limits` checks it.
DAY_LIMITS = {"minute": 60, "3minute": 100, "5minute": 100, "10minute": 100, "15minute": 200,
              "30minute": 200, "60minute": 400, "day": 2000}  # fmt: skip


def windows(start: datetime, end: datetime, days: int) -> list[tuple[datetime, datetime]]:
    out, cur = [], start
    step = timedelta(days=days)
    while cur < end:
        nxt = min(cur + step, end)
        out.append((cur, nxt))
        cur = nxt
    return out


class KiteProvider:
    def __init__(
        self, client: KiteClient, instruments: list[Instrument] | None = None,
        day_limit: int = DAY_LIMITS["minute"],
    ) -> None:  # fmt: skip
        self.client, self._instruments, self.day_limit = client, instruments or [], day_limit
        self._last_error: str | None = None

    def list_instruments(self) -> list[Instrument]:
        return list(self._instruments)

    def historical(
        self, instrument: Instrument, tf: str, start: datetime, end: datetime
    ) -> Iterable[Bar]:
        if tf != "1m":
            raise ProviderError(ErrorCode.BAD_DATA, "only 1m is stored (D08); resample instead")
        if instrument.provider_token is None:
            raise ProviderError(ErrorCode.BAD_DATA, f"{instrument.instrument_id} has no token")
        seen: dict[datetime, Bar] = {}
        try:
            for a, b in windows(start, end, self.day_limit):
                candles = self.client.historical(instrument.provider_token, "minute", a, b)
                try:
                    bars = parse_kite_candles(candles, instrument_id=instrument.instrument_id)
                except ImportRejected as e:
                    raise ProviderError(ErrorCode.BAD_DATA, str(e)) from e
                for bar in bars:
                    if instrument.instrument_type == "INDEX":  # index spot has no volume (D20)
                        bar = bar.model_copy(update={"volume": 0.0, "volume_kind": "absent"})
                    seen[bar.bar_start_utc] = bar
        except ProviderError as e:
            self._last_error = str(e)
            raise
        self._last_error = None
        return [seen[k] for k in sorted(seen) if start <= k < end]

    def stream(self, instruments: Sequence[Instrument], mode: str) -> AsyncIterator[Tick]:
        raise NotImplementedError("Kite WebSocket stream arrives with C08")

    def status(self) -> dict[str, Any]:
        return {"provider": "kite", "authenticated": repr(self.client).endswith("True)"),
                "last_error": self._last_error}  # fmt: skip
