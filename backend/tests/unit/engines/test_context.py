from datetime import date

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nifty.contracts import Bar, Instrument
from nifty.engines.context import ConfigError, EngineContext
from nifty.marketdata.resample import resample
from tests.helpers import CAL, day_bars

INS = Instrument(instrument_id="csv:T", provider="csv", tradingsymbol="T", tick_size=0.05)


def ctx_with(bars: list[Bar], tf: str = "5m", **kw: object) -> EngineContext:
    c = EngineContext(INS, tf, CAL, **kw)  # type: ignore[arg-type]
    for b in bars:
        c.append_1m(b)
    return c


def test_prior_day_is_previous_session_present_in_the_data() -> None:
    # 2026-11-10 has no data in the oracle: Wed 11-11 must see Mon 11-09, not a calendar weekday
    mon, wed = day_bars(date(2026, 11, 9)), day_bars(date(2026, 11, 11))
    c = ctx_with(mon + wed)
    assert c.prior_day(mon[5]) is None  # first session of the dataset
    pd = c.prior_day(wed[0])
    assert pd is not None and pd.date == date(2026, 11, 9)
    assert pd.high == max(b.high for b in mon) and pd.low == min(b.low for b in mon)
    assert pd.close == mon[-1].close
    assert c.prior_day(wed[100]) == pd  # same answer anywhere in the later session


def test_htf_new_bar_and_completed() -> None:
    bars = day_bars(date(2026, 11, 2))
    c = ctx_with(bars, "5m")
    first = resample(bars[:5], "5m", CAL)[0]
    assert c.htf(first, "1h").new_bar and c.htf(first, "1h").completed is None
    mid = resample(bars[5:10], "5m", CAL)[0]
    assert c.htf(mid, "1h") == c.htf(mid, "1h") and not c.htf(mid, "1h").new_bar
    nxt = resample(bars[60:65], "5m", CAL)[0]  # 10:15, the second hourly bucket
    step = c.htf(nxt, "1h")
    done = step.completed
    assert step.new_bar and done is not None
    assert (done.open, done.close) == (bars[0].open, bars[59].close)
    assert done.high == max(b.high for b in bars[:60]) and done.timeframe == "1h" and done.finalized


def test_sub_bars_rules() -> None:
    bars = day_bars(date(2026, 11, 2))
    c15 = ctx_with(bars[:7], "15m")
    chart = resample(bars, "15m", CAL)[0]
    assert len(c15.sub_bars(chart, "1m")) == 7  # only what exists below the bar's end
    assert [b.timeframe for b in c15.sub_bars(chart, "5m")] == ["5m"]  # 5m #2 (5-9) is partial
    c15.provisional = True
    assert len(c15.sub_bars(chart, "5m")) == 2  # the forming one is included for on_provisional
    for bad in ("15m", "1h", "7m", "10m", "1d"):  # not shorter / unknown / does not divide 15
        with pytest.raises(ConfigError):
            c15.sub_bars(chart, bad)


def test_proxy_volume_needs_every_minute() -> None:
    bars = day_bars(date(2026, 11, 2))[:5]
    chart = resample(bars, "5m", CAL)[0]
    full = {b.bar_start_utc: 10.0 for b in bars}
    assert ctx_with(bars, proxy_volume_1m=full).proxy_volume(chart) == 50.0
    del full[bars[2].bar_start_utc]
    assert ctx_with(bars, proxy_volume_1m=full).proxy_volume(chart) is None
    assert ctx_with(bars).proxy_volume(chart) is None


def test_mintick_is_never_invented() -> None:
    c = EngineContext(INS.model_copy(update={"tick_size": None}), "5m", CAL)
    with pytest.raises(ConfigError):
        _ = c.mintick
    assert ctx_with([]).mintick == 0.05


def test_append_must_be_ordered_and_1m() -> None:
    bars = day_bars(date(2026, 11, 2))
    c = ctx_with(bars[:3])
    with pytest.raises(ValueError):
        c.append_1m(bars[1])
    with pytest.raises(ValueError):
        c.append_1m(resample(bars[:5], "5m", CAL)[0])


@st.composite
def ragged(draw: st.DrawFn) -> list[Bar]:
    days = draw(
        st.lists(
            st.sampled_from([date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 5)]),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )
    out: list[Bar] = []
    for d in sorted(days):
        gone = draw(st.sets(st.integers(0, 374), max_size=60))
        out += [b for i, b in enumerate(day_bars(d)) if i not in gone]
    return out


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ragged(), st.sampled_from(["5m", "15m", "1h"]), st.data())
def test_answers_never_change_when_future_bars_are_appended(
    bars: list[Bar], tf: str, data: st.DataObject
) -> None:
    chart = [b for b in resample(bars, tf, CAL) if b.finalized]
    if not chart:
        return
    proxy = {b.bar_start_utc: 1.0 + i % 3 for i, b in enumerate(bars)}
    for cb in data.draw(st.lists(st.sampled_from(chart), min_size=1, max_size=3)):
        past = [b for b in bars if b.bar_start_utc < cb.bar_end_utc]
        a = ctx_with(past, tf, proxy_volume_1m=proxy)
        b = ctx_with(bars, tf, proxy_volume_1m=proxy)  # same plus every future bar
        assert a.prior_day(cb) == b.prior_day(cb)
        assert a.htf(cb, "15m") == b.htf(cb, "15m")
        assert a.htf(cb, "1d") == b.htf(cb, "1d")
        assert a.sub_bars(cb, "1m") == b.sub_bars(cb, "1m")
        assert a.proxy_volume(cb) == b.proxy_volume(cb)
        if tf != "5m":
            assert a.sub_bars(cb, "5m") == b.sub_bars(cb, "5m")
