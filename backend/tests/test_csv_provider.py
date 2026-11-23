from datetime import UTC, datetime

import pytest

from nifty.contracts import Instrument
from nifty.marketdata.base import ErrorCode, ProviderError
from nifty.marketdata.providers.csv_replay import CsvReplayProvider
from tests.helpers import CAL, ORACLE

INS = Instrument(
    instrument_id="csv:NIFTY 50", provider="csv", tradingsymbol="NIFTY 50", tick_size=0.05
)
LO, HI = datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)


def test_historical_1m_and_5m() -> None:
    p = CsvReplayProvider(ORACLE, INS, calendar=CAL)
    assert p.list_instruments() == [INS]
    assert len(list(p.historical(INS, "1m", LO, HI))) == 5996
    five = list(p.historical(INS, "5m", LO, HI))
    assert five and all(b.timeframe == "5m" for b in five)
    assert p.status()["rows_ok"] == 5996 and p.status()["ok"]


def test_range_filter() -> None:
    p = CsvReplayProvider(ORACLE, INS, calendar=CAL)
    day = datetime(2026, 10, 23, tzinfo=UTC)
    got = list(p.historical(INS, "1m", day, datetime(2026, 10, 24, tzinfo=UTC)))
    assert got and all(day <= b.bar_start_utc < datetime(2026, 10, 24, tzinfo=UTC) for b in got)


def test_unknown_instrument_and_stream() -> None:
    p = CsvReplayProvider(ORACLE, INS, calendar=CAL)
    other = INS.model_copy(update={"instrument_id": "csv:OTHER"})
    with pytest.raises(ProviderError) as e:
        p.historical(other, "1m", LO, HI)
    assert e.value.code is ErrorCode.BAD_DATA
    with pytest.raises(NotImplementedError):
        p.stream([INS], "ltp")
