"""CSV replay provider: serves validated, resampled bars from a local 1m file. No DB, no network."""

from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from nifty.contracts import Bar, Instrument
from nifty.marketdata.base import ErrorCode, ProviderError, Tick
from nifty.marketdata.importer import ImportRejected, parse_file
from nifty.marketdata.resample import resample
from nifty.marketdata.validation import validate_bars
from nifty.timeutil import Calendar


class CsvReplayProvider:
    def __init__(
        self,
        path: Path,
        instrument: Instrument,
        tz: str | None = None,
        calendar: Calendar | None = None,
    ) -> None:
        self.path, self.instrument, self.tz = path, instrument, tz
        self.calendar = calendar or Calendar.load()
        self._last_report: dict[str, Any] = {}

    def list_instruments(self) -> list[Instrument]:
        return [self.instrument]

    def historical(
        self, instrument: Instrument, tf: str, start: datetime, end: datetime
    ) -> Iterable[Bar]:
        if instrument.instrument_id != self.instrument.instrument_id:
            raise ProviderError(
                ErrorCode.BAD_DATA, f"unknown instrument {instrument.instrument_id}"
            )
        try:
            raw = parse_file(self.path, instrument_id=instrument.instrument_id, tz=self.tz)
        except (ImportRejected, OSError) as e:
            raise ProviderError(ErrorCode.BAD_DATA, str(e)) from e
        bars, report = validate_bars(raw, self.calendar)
        self._last_report = {"rows_in": report.rows_in, "rows_ok": report.rows_ok}
        out = bars if tf == "1m" else resample(bars, tf, self.calendar)
        return [b for b in out if start <= b.bar_start_utc < end]

    def stream(self, instruments: Sequence[Instrument], mode: str) -> AsyncIterator[Tick]:
        raise NotImplementedError("CSV replay streaming arrives in C08")

    def status(self) -> dict[str, Any]:
        return {
            "provider": "csv_replay",
            "path": str(self.path),
            "ok": self.path.exists(),
            **self._last_report,
        }
