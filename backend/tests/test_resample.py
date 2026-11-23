from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nifty.contracts import Bar
from nifty.marketdata.resample import resample
from nifty.marketdata.validation import validate_bars
from nifty.timeutil import IST
from tests.helpers import CAL, ORACLE, day_bars

D1, D2 = date(2026, 11, 2), date(2026, 11, 3)


def hm(b: Bar) -> str:
    return b.bar_start_utc.astimezone(IST).strftime("%H:%M")


def test_full_day_5m_and_1h_and_1d() -> None:
    bars = day_bars(D1)
    five = resample(bars, "5m", CAL)
    assert len(five) == 75 and hm(five[0]) == "09:15" and all(b.finalized for b in five)
    assert five[0].open == bars[0].open and five[0].close == bars[4].close
    assert five[0].volume == sum(b.volume for b in bars[:5]) and five[0].high == max(
        b.high for b in bars[:5]
    )
    hour = resample(bars, "1h", CAL)
    assert [hm(b) for b in hour][-2:] == ["14:15", "15:15"]
    assert "partial_bucket" in hour[-1].quality_flags and hour[-1].bar_end_utc - hour[
        -1
    ].bar_start_utc == timedelta(minutes=15)
    assert "partial_bucket" not in hour[0].quality_flags
    day = resample(bars, "1d", CAL)
    assert len(day) == 1 and day[0].bar_end_utc - day[0].bar_start_utc == timedelta(minutes=375)
    assert day[0].finalized and not day[0].quality_flags


def test_10m_and_30m_structural_partials() -> None:
    bars = day_bars(D1)
    assert "partial_bucket" in resample(bars, "10m", CAL)[-1].quality_flags
    assert hm(resample(bars, "10m", CAL)[-1]) == "15:25"
    assert "partial_bucket" in resample(bars, "30m", CAL)[-1].quality_flags


def test_session_ending_14_48_is_partial_and_unfinalized() -> None:
    # offsets 0..333 = 09:15..14:48 (inclusive)
    five = resample(day_bars(D1, 0, 333), "5m", CAL)
    last = five[-1]
    assert hm(last) == "14:45" and "partial_bucket" in last.quality_flags and not last.finalized
    assert all(b.finalized for b in five[:-1])
    assert not resample(day_bars(D1, 0, 333), "1d", CAL)[0].finalized


def test_missing_14_49_with_later_bar_is_finalized_with_gap() -> None:
    # 14:49 = offset 334; present 14:50 (335) proves the bucket is done
    bars = day_bars(D1, 0, 374, skip=frozenset({334}))
    b = next(x for x in resample(bars, "5m", CAL) if hm(x) == "14:45")
    assert (
        b.finalized and "gap_before" in b.quality_flags and "partial_bucket" not in b.quality_flags
    )
    assert b.volume == sum(
        x.volume
        for x in bars
        if 330 <= (x.bar_start_utc - CAL.session_bounds(D1)[0]).seconds // 60 < 335
    )


def test_partial_first_session_start_1450() -> None:
    # offsets 335..374 = 14:50..15:29 (40 bars)
    bars = day_bars(D1, 335, 374)
    hour = resample(bars, "1h", CAL)
    assert [hm(b) for b in hour] == ["14:15", "15:15"] and "partial_bucket" in hour[0].quality_flags
    assert [hm(b) for b in resample(bars, "5m", CAL)][0] == "14:50"
    assert "partial_bucket" in resample(bars, "1d", CAL)[0].quality_flags


def test_does_not_straddle_sessions() -> None:
    bars = day_bars(D1) + day_bars(D2)
    day = resample(bars, "1d", CAL)
    assert len(day) == 2 and day[0].bar_end_utc <= day[1].bar_start_utc
    assert len(resample(bars, "1h", CAL)) == 14


def test_oracle_last_session_tail() -> None:
    from nifty.marketdata.importer import parse_csv

    ok, _ = validate_bars(parse_csv(ORACLE, instrument_id="csv:NIFTY 50"), CAL)
    five = resample(ok, "5m", CAL)
    assert not five[-1].finalized and hm(five[-1]) == "14:45"
    gap_day = [
        b
        for b in five
        if b.bar_start_utc.astimezone(IST).date() == date(2026, 10, 26) and hm(b) == "14:45"
    ]
    assert gap_day[0].finalized and "gap_before" in gap_day[0].quality_flags


@st.composite
def series(draw: st.DrawFn) -> list[Bar]:
    days = draw(
        st.lists(
            st.sampled_from([date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )
    out: list[Bar] = []
    for d in sorted(days):
        n = 375
        keep = draw(st.lists(st.integers(0, n - 1), min_size=1, max_size=120, unique=True))
        out += [b for i, b in enumerate(day_bars(d)) if i in set(keep)]
    return out


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(series(), st.sampled_from(["3m", "5m", "10m", "15m", "30m", "1h", "1d"]))
def test_resample_properties(bars: list[Bar], tf: str) -> None:
    out = resample(bars, tf, CAL)
    assert sum(b.volume for b in out) == sum(b.volume for b in bars)
    for o in out:
        d = CAL.session_date(o.bar_start_utc)
        s_open, s_close = CAL.session_bounds(d)
        assert s_open <= o.bar_start_utc < o.bar_end_utc <= s_close  # never straddles
        members = [b for b in bars if o.bar_start_utc <= b.bar_start_utc < o.bar_end_utc]
        assert members
        assert o.high == max(b.high for b in members) and o.low == min(b.low for b in members)
        assert o.open == members[0].open and o.close == members[-1].close
    assert resample(out, tf, CAL) == out  # idempotent on its own grid
