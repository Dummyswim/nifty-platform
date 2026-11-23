from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from nifty.contracts import Bar
from nifty.marketdata.importer import ImportRejected, parse_csv, parse_kite_candles
from nifty.marketdata.validation import validate_bars
from tests.helpers import CAL, bar, day_bars

D = date(2026, 11, 2)  # a Monday
OPEN = CAL.session_bounds(D)[0]


def reasons(bars: list[Bar]) -> list[str]:
    return [e.reason for e in validate_bars(bars, CAL)[1].excluded]


def test_clean_day() -> None:
    ok, r = validate_bars(day_bars(D), CAL)
    assert r.rows_ok == 375 and not r.gaps and not r.excluded and r.sessions[0].n == 375
    assert [b.revision for b in ok] == [0] * 375


def test_off_grid_seconds_not_floored() -> None:
    assert reasons([bar(OPEN + timedelta(seconds=30))]) == ["off_grid"]


def test_session_and_weekend_exclusion() -> None:
    assert reasons([bar(OPEN - timedelta(minutes=1))]) == ["off_session"]
    assert reasons([bar(OPEN + timedelta(minutes=375))]) == ["off_session"]
    sat = CAL.session_bounds(date(2026, 11, 7))[0]
    assert reasons([bar(sat)]) == ["non_session_day"]


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"lo": 100.7, "c": 100.8}, "bad_ohlc"),
        ({"h": 100.0, "o": 100.2}, "bad_ohlc"),
        ({"o": float("nan")}, "non_finite"),
        ({"v": -1.0}, "bad_volume"),
        ({"v": float("nan")}, "bad_volume"),
    ],
)
def test_row_rejections(kw: dict[str, float], reason: str) -> None:
    assert reasons([bar(OPEN, **kw)]) == [reason]  # type: ignore[arg-type]


def test_identical_duplicate_dropped_differing_revised() -> None:
    a, same, diff = bar(OPEN), bar(OPEN), bar(OPEN, c=100.25)
    ok, r = validate_bars([a, same, diff], CAL)
    assert r.duplicates == 1 and [b.revision for b in ok] == [0, 1] and ok[1].close == 100.25


def test_out_of_order_reported_and_sorted() -> None:
    t1 = OPEN + timedelta(minutes=1)
    ok, r = validate_bars([bar(t1), bar(OPEN)], CAL)
    assert r.out_of_order == 1 and [b.bar_start_utc for b in ok] == [OPEN, t1]


def test_gap_detected_and_next_bar_flagged() -> None:
    ok, r = validate_bars(day_bars(D, skip=frozenset({10, 11, 12})), CAL)
    assert len(r.gaps) == 1 and r.gaps[0].missing == 3
    flagged = [b for b in ok if "gap_before" in b.quality_flags]
    assert [b.bar_start_utc for b in flagged] == [OPEN + timedelta(minutes=13)]


def test_leading_and_trailing_absence_is_not_a_gap() -> None:
    _, r = validate_bars(day_bars(D, 5, 300), CAL)
    assert not r.gaps and r.sessions[0].n == 296


def test_nonzero_volume_stays_exchange() -> None:
    ok, r = validate_bars(day_bars(D, 0, 5), CAL)
    assert r.volume_kind == "exchange" and "volume_absent" not in ok[0].quality_flags


def test_naive_timestamp_rejected_unless_tz(tmp_path: Path) -> None:
    p = tmp_path / "n.csv"
    p.write_text("timestamp,open,high,low,close,volume\n2026-11-02T09:15:00,1,2,1,2,0\n")
    with pytest.raises(ImportRejected):
        parse_csv(p, instrument_id="csv:T")
    b = parse_csv(p, instrument_id="csv:T", tz="Asia/Kolkata")[0]
    assert b.bar_start_utc == datetime(2026, 11, 2, 3, 45, tzinfo=UTC)


def test_non_1m_rejected(tmp_path: Path) -> None:
    p = tmp_path / "f.csv"
    p.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-11-02T09:15:00+05:30,1,2,1,2,0\n2026-11-02T09:20:00+05:30,1,2,1,2,0\n"
    )
    with pytest.raises(ImportRejected):
        parse_csv(p, instrument_id="csv:T")
    with pytest.raises(ImportRejected):
        parse_csv(p, instrument_id="csv:T", timeframe="5m")


def test_kite_candles_with_compact_offset() -> None:
    bars = parse_kite_candles(
        [["2026-11-02T09:15:00+0530", 1, 2, 0.5, 1.5, 100, 7]], instrument_id="kite:NSE:X"
    )
    assert bars[0].bar_start_utc == datetime(2026, 11, 2, 3, 45, tzinfo=UTC)
    assert bars[0].provider == "kite" and bars[0].volume == 100
