"""Known-answer tests: every expected value is worked out by hand from the Pine definition."""

import json
import math
import random
from collections.abc import Sequence
from typing import Any

import pytest

import nifty.engines.pinekit as pk
from tests.helpers import CAL, day_bars

NaN = math.nan


def feed(ind: Any, xs: Sequence[float]) -> list[float]:
    return [ind.update(x) for x in xs]


def same(got: list[float], want: list[float]) -> None:
    assert len(got) == len(want)
    for g, w in zip(got, want, strict=True):
        assert (math.isnan(g) and math.isnan(w)) or g == pytest.approx(w, abs=1e-12), (got, want)


def test_na_helpers_and_nan_propagating_max_min() -> None:
    assert pk.isna(NaN) and not pk.isna(0.0)
    assert pk.nz(NaN) == 0.0 and pk.nz(NaN, 7) == 7 and pk.nz(3.0) == 3.0
    assert math.isnan(pk.max(NaN, 1.0)) and math.isnan(pk.max(1.0, NaN))  # builtin gives 1.0
    assert math.isnan(pk.min(1.0, NaN)) and pk.max(1.0, 2.0, 3.0) == 3.0 and pk.min(2.0, 1.0) == 1.0


def test_series_indexing() -> None:
    s = pk.Series(3)
    for x in (1.0, 2.0, 3.0, 4.0):
        s.push(x)
    # capacity 3 keeps [2,3,4]: s[0]=4, s[1]=3, s[2]=2, older = na
    assert (
        (s[0], s[1], s[2]) == (4.0, 3.0, 2.0) and math.isnan(s[3]) and math.isnan(pk.Series(2)[0])
    )


def test_sma_sum_highest_lowest_stdev() -> None:
    xs = [3.0, 1.0, 4.0, 1.0, 5.0]
    # sma(3): (3+1+4)/3 = 8/3, (1+4+1)/3 = 2, (4+1+5)/3 = 10/3
    same(feed(pk.Sma(3), xs), [NaN, NaN, 8 / 3, 2.0, 10 / 3])
    same(feed(pk.Sum(3), xs), [NaN, NaN, 8.0, 6.0, 10.0])
    same(feed(pk.Highest(3), xs), [NaN, NaN, 4.0, 4.0, 5.0])
    same(feed(pk.Lowest(3), xs), [NaN, NaN, 1.0, 1.0, 1.0])
    # stdev(3) of 1,2,3: mean 2, population variance (1+0+1)/3 = 2/3
    same(feed(pk.Stdev(3), [1.0, 2.0, 3.0]), [NaN, NaN, math.sqrt(2 / 3)])
    # an na inside the window makes the result na until it leaves the window
    same(feed(pk.Sma(2), [1.0, NaN, 3.0, 5.0]), [NaN, NaN, NaN, 4.0])


def test_windowed_stats_do_not_drift_at_index_prices() -> None:
    base = 25000.0
    xs = [base + 0.05 * (i % 7) for i in range(2000)]
    s = pk.Sma(14)
    out = feed(s, xs)
    last = xs[-14:]
    assert out[-1] == pytest.approx(math.fsum(last) / 14, abs=1e-9)


def test_ema_seed_first_and_sma() -> None:
    # len 3 -> alpha = 2/4 = 0.5 (exact in binary). inputs 2,4,6,8
    # first: 2 ; 0.5*4+0.5*2 = 3 ; 0.5*6+0.5*3 = 4.5 ; 0.5*8+0.5*4.5 = 6.25
    same(feed(pk.Ema(3), [2.0, 4.0, 6.0, 8.0]), [2.0, 3.0, 4.5, 6.25])
    # sma seed: NaN, NaN, sma(2,4,6) = 4 ; 0.5*8+0.5*4 = 6
    same(feed(pk.Ema(3, "sma"), [2.0, 4.0, 6.0, 8.0]), [NaN, NaN, 4.0, 6.0])
    with pytest.raises(ValueError):
        pk.Ema(3, "nope")


def test_rma() -> None:
    # len 2 -> alpha 0.5. inputs 2,4,6,8: NaN ; sma(2,4) = 3 ; (3*1+6)/2 = 4.5 ; (4.5*1+8)/2 = 6.25
    same(feed(pk.Rma(2), [2.0, 4.0, 6.0, 8.0]), [NaN, 3.0, 4.5, 6.25])


def test_tr_and_atr() -> None:
    bars = [(10.0, 8.0, 9.0), (11.0, 9.0, 10.0), (12.0, 7.0, 8.0), (15.0, 13.0, 14.0)]
    tr = pk.Tr()
    # bar1: first bar = 10-8 = 2
    # bar2: max(11-9=2, |11-9|=2, |9-9|=0) = 2
    # bar3: max(12-7=5, |12-10|=2, |7-10|=3) = 5
    # bar4 (gap up, prev close 8): max(15-13=2, |15-8|=7, |13-8|=5) = 7
    same([tr.update(*b) for b in bars], [2.0, 2.0, 5.0, 7.0])
    # atr len 2 = rma(tr): NaN ; (2+2)/2 = 2 ; (2*1+5)/2 = 3.5 ; (3.5*1+7)/2 = 5.25
    atr = pk.Atr(2)
    same([atr.update(*b) for b in bars], [NaN, 2.0, 3.5, 5.25])


def test_atr_sess_resets_tr_at_session_start_but_keeps_smoothing() -> None:
    bars = [(10.0, 8.0, 9.0), (11.0, 9.0, 10.0), (12.0, 7.0, 8.0), (15.0, 13.0, 14.0)]
    a = pk.AtrSess(2)
    got = [a.update(*b, new_session=(i == 3)) for i, b in enumerate(bars)]
    # bar4 opens a session: TR = 15-13 = 2 (not 7); rma = (3.5*1+2)/2 = 2.75
    same(got, [NaN, 2.0, 3.5, 2.75])


def test_rsi() -> None:
    # len 2. closes 10,11,10,12 -> changes +1,-1,+2
    # up inputs 1,0,2 -> rma seed (1+0)/2 = 0.5, then (0.5*1+2)/2 = 1.25
    # dn inputs 0,1,0 -> rma seed (0+1)/2 = 0.5, then (0.5*1+0)/2 = 0.25
    # rsi = 100 - 100/(1+up/dn): bar3 -> 100-100/2 = 50 ; bar4 -> 100-100/(1+5) = 83.333...
    same(feed(pk.Rsi(2), [10.0, 11.0, 10.0, 12.0]), [NaN, NaN, 50.0, 100 - 100 / 6])
    same(feed(pk.Rsi(2), [1.0, 2.0, 3.0]), [NaN, NaN, 100.0])  # dn == 0
    same(feed(pk.Rsi(2), [3.0, 2.0, 1.0]), [NaN, NaN, 0.0])  # up == 0
    same(feed(pk.Rsi(2), [5.0, 5.0, 5.0]), [NaN, NaN, 100.0])  # both 0 -> 100 per Pine


def test_crossover_crossunder_and_change() -> None:
    a, b = [1.0, 3.0, 3.0, 2.0], [2.0, 2.0, 3.0, 3.0]
    up, dn = pk.Crossover(), pk.Crossunder()
    # bar1 no history; bar2 3>2 and 1<=2 -> up; bar3 3>3 false; bar4 2<3 and 3>=3 -> down
    assert [up.update(x, y) for x, y in zip(a, b, strict=True)] == [False, True, False, False]
    assert [dn.update(x, y) for x, y in zip(a, b, strict=True)] == [False, False, False, True]
    assert not pk.Crossover().update(NaN, 1.0)
    same(feed(pk.Change(1), [5.0, 7.0, 4.0]), [NaN, 2.0, -3.0])
    same(feed(pk.Change(2), [5.0, 7.0, 4.0]), [NaN, NaN, -1.0])


def test_pivots_and_tie_policy() -> None:
    # left=right=2: bar index 4 confirms index 2
    same(feed(pk.PivotHigh(2, 2), [1.0, 3.0, 5.0, 3.0, 1.0]), [NaN, NaN, NaN, NaN, 5.0])
    same(feed(pk.PivotLow(2, 2), [5.0, 3.0, 1.0, 3.0, 5.0]), [NaN, NaN, NaN, NaN, 1.0])
    right_tie = [1.0, 3.0, 5.0, 5.0, 1.0]
    assert feed(pk.PivotHigh(2, 2), right_tie)[-1] == 5.0  # default: >= right bars
    assert math.isnan(feed(pk.PivotHigh(2, 2, "strict"), right_tie)[-1])
    left_tie = [3.0, 5.0, 5.0, 3.0, 1.0]
    assert math.isnan(feed(pk.PivotHigh(2, 2), left_tie)[-1])  # strictly greater than left bars
    with pytest.raises(ValueError):
        pk.PivotHigh(2, 2, "x")


def test_round_to_mintick_half_up_with_epsilon() -> None:
    # 100.025/0.05 = 2000.5 (a hair under in binary): +0.5 -> 2001 -> 100.05 (half up)
    assert pk.round_to_mintick(100.025, 0.05) == pytest.approx(100.05)
    assert pk.round_to_mintick(100.02, 0.05) == pytest.approx(100.0)  # 2000.4 + .5 -> 2000
    assert pk.round_to_mintick(100.03, 0.05) == pytest.approx(100.05)  # 2000.6 + .5 -> 2001
    assert math.isnan(pk.round_to_mintick(NaN, 0.05))


@pytest.mark.parametrize(
    "make",
    [
        lambda: pk.Sma(4), lambda: pk.Stdev(4), lambda: pk.Highest(3), lambda: pk.Ema(5, "sma"),
        lambda: pk.Ema(5), lambda: pk.Rma(4), lambda: pk.Rsi(4), lambda: pk.Change(2),
        lambda: pk.PivotHigh(2, 2), lambda: pk.PivotLow(2, 1),
    ],
)  # fmt: skip
def test_state_roundtrip_is_json_safe_and_exact(make) -> None:  # type: ignore[no-untyped-def]
    rng = random.Random(7)
    xs = [25000 + rng.random() * 50 for _ in range(30)]
    xs[3] = NaN  # na in the stream must survive allow_nan=False
    full = make()
    ref = feed(full, xs)
    part = make()
    feed(part, xs[:17])
    snap = json.loads(json.dumps(part.state(), allow_nan=False))
    fresh = make()
    fresh.load(snap)
    same(feed(fresh, xs[17:]), ref[17:])


def test_tr_atr_atr_sess_cross_state_roundtrip() -> None:
    hlc = [(12.0, 8.0, 9.0), (13.0, 9.0, 10.0), (11.0, 7.0, 8.0), (15.0, 12.0, 14.0)]

    def roundtrip(a: Any, b: Any) -> None:
        b.load(json.loads(json.dumps(a.state(), allow_nan=False)))

    for make in (pk.Tr, lambda: pk.Atr(2), lambda: pk.AtrSess(2)):
        a, b = make(), make()
        a.update(*hlc[0])
        a.update(*hlc[1])
        roundtrip(a, b)
        assert [a.update(*x) for x in hlc[2:]] == [b.update(*x) for x in hlc[2:]]
    c, d = pk.Crossover(), pk.Crossover()
    c.update(1.0, 2.0)
    roundtrip(c, d)
    assert d.update(3.0, 2.0) is True


def test_session_helpers() -> None:
    from datetime import date

    day = date(2026, 11, 2)
    bars = day_bars(day)
    assert pk.bar_minutes_ist(bars[0].bar_start_utc) == 9 * 60 + 15
    assert pk.bar_minutes_ist(bars[-1].bar_end_utc) == 15 * 60 + 30
    assert pk.is_new_session(bars[0], None, CAL) and not pk.is_new_session(bars[1], bars[0], CAL)
    nxt = day_bars(date(2026, 11, 3))[0]
    assert pk.is_new_session(nxt, bars[-1], CAL)
    assert pk.is_last_bar_of_session(bars[-1], CAL) and not pk.is_last_bar_of_session(bars[-2], CAL)
    assert not pk.is_last_bar_of_session(bars[0], CAL)  # decided by the calendar, not by lookahead
    # timeframe.change: 1h buckets open at 09:15, 10:15 ...
    assert pk.timeframe_change(bars[60], bars[59], "1h", CAL)
    assert not pk.timeframe_change(bars[61], bars[60], "1h", CAL)
    assert pk.timeframe_change(nxt, bars[-1], "1d", CAL) and not pk.timeframe_change(
        bars[5], bars[4], "1d", CAL
    )
    assert pk.bucket_start("5m", bars[7].bar_start_utc, CAL) == bars[5].bar_start_utc
