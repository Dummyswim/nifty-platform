"""CSV, JSON and Kite-candle parsers to 1m Bars. 1m only (D08); naive timestamps need a tz."""

import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from nifty.contracts import Bar
from nifty.timeutil import utcnow

ONE_MIN = timedelta(minutes=1)


class ImportRejected(ValueError):
    """The input cannot be imported as 1m bars (reported, never repaired)."""


def _parse_ts(raw: str, tz: str | None) -> datetime:
    s = raw.strip()
    try:
        ts = datetime.fromisoformat(s)
    except ValueError:
        try:
            ts = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError as e:
            raise ImportRejected(f"unparseable timestamp {raw!r}") from e
    if ts.tzinfo is None:
        if tz is None:
            raise ImportRejected(f"naive timestamp {raw!r}; pass tz (e.g. Asia/Kolkata)")
        ts = ts.replace(tzinfo=ZoneInfo(tz))
    return ts.astimezone(UTC)


def _num(v: Any, what: str, n: int) -> float:
    try:
        return float(v)
    except (TypeError, ValueError) as e:
        raise ImportRejected(f"row {n}: bad {what} {v!r}") from e


def _build(
    rows: Iterable[Sequence[Any]],
    *,
    instrument_id: str,
    provider: str,
    tz: str | None,
    timeframe: str,
) -> list[Bar]:
    if timeframe != "1m":
        raise ImportRejected(f"only 1m bars can be imported (got {timeframe}); resample instead")
    now = utcnow()
    bars: list[Bar] = []
    for n, (ts_raw, o, h, lo, c, v) in enumerate(rows, 1):
        t = _parse_ts(str(ts_raw), tz)
        bars.append(
            Bar(
                instrument_id=instrument_id,
                provider=provider,
                timeframe="1m",
                bar_start_utc=t,
                bar_end_utc=t + ONE_MIN,
                open=_num(o, "open", n),
                high=_num(h, "high", n),
                low=_num(lo, "low", n),
                close=_num(c, "close", n),
                volume=_num(v, "volume", n),
                received_at_utc=now,
            )
        )
    _check_spacing(bars)
    return bars


def _check_spacing(bars: list[Bar]) -> None:
    """Reject files whose smallest step between consecutive rows is not one minute."""
    deltas = [
        b.bar_start_utc - a.bar_start_utc
        for a, b in zip(bars, bars[1:], strict=False)
        if b.bar_start_utc > a.bar_start_utc
    ]
    if deltas and min(deltas) > ONE_MIN:
        raise ImportRejected(f"not 1m data (smallest step {min(deltas)})")


def parse_csv(
    path: Path,
    *,
    instrument_id: str,
    provider: str = "csv",
    tz: str | None = None,
    timeframe: str = "1m",
) -> list[Bar]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        need = ["timestamp", "open", "high", "low", "close", "volume"]
        if reader.fieldnames is None or any(k not in reader.fieldnames for k in need):
            raise ImportRejected(f"CSV needs columns {need}")
        rows = [[r[k] for k in need] for r in reader]
    return _build(rows, instrument_id=instrument_id, provider=provider, tz=tz, timeframe=timeframe)


def parse_json(
    path: Path,
    *,
    instrument_id: str,
    provider: str = "csv",
    tz: str | None = None,
    timeframe: str = "1m",
) -> list[Bar]:
    data: list[Mapping[str, Any]] = json.loads(path.read_text())
    rows = [[d["timestamp"], d["open"], d["high"], d["low"], d["close"], d["volume"]] for d in data]
    return _build(rows, instrument_id=instrument_id, provider=provider, tz=tz, timeframe=timeframe)


def parse_kite_candles(
    candles: Sequence[Sequence[Any]],
    *,
    instrument_id: str,
    tz: str | None = None,
    timeframe: str = "1m",
) -> list[Bar]:
    """Kite arrays [ts, o, h, l, c, v(, oi)]; ts like 2026-11-16T09:15:00+0530."""
    rows = [list(c[:6]) for c in candles]
    return _build(rows, instrument_id=instrument_id, provider="kite", tz=tz, timeframe=timeframe)


def parse_file(path: Path, **kw: Any) -> list[Bar]:
    return (parse_json if path.suffix.lower() == ".json" else parse_csv)(path, **kw)
