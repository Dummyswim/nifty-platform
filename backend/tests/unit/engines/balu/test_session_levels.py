"""Steps 1-3 on hand-built bars: prior day, PDC dual add, OR window boundary, HTF once per HTF bar."""

from typing import Any

import pytest

from nifty.engines.context import ConfigError
from tests.unit.engines.balu.helpers import D1, D2, OHLC, Harness

BASE: dict[str, Any] = dict(
    use_htf_levels=False, swing_len=10, or_minutes=120, dedupe_atr=0.05, prune_atr=60.0
)


def rising(start: float, n: int) -> list[OHLC]:
    """Bar i: o=start+i, h=o+1, l=o-1, c=o+0.5. TR is 2 every bar, so ATR(14) is exactly 2."""
    return [(start + i, start + i + 1, start + i - 1, start + i + 0.5) for i in range(n)]


def test_first_session_has_no_prior_day_and_an_empty_pool() -> None:
    h = Harness(**BASE)
    h.day(D1, rising(100, 20))
    assert h.plot("pool_size") == [0.0] * 20  # no pivots on a straight ramp, nothing to carry in


def test_prior_close_is_added_as_both_flags_and_the_or_window_closes_at_orbars_plus_one() -> None:
    h = Harness(**BASE)
    h.day(D1, rising(100, 20))  # day high 120, low 99, close 119.5
    h.day(D2, rising(121, 26))
    pool = h.plot("pool_size")[20:]
    # new session: pdH(high) pdL(low) pdC(high) pdC(low) = 4 entries; |120 - 119.5| > 0.05*atr
    assert pool[0] == 4.0
    assert pool[:24] == [4.0] * 24
    # orBars = ceil(120 / 5) = 24: the OR high/low enter the pool at dayLen == 25 (index 24)
    assert pool[24:] == [6.0, 6.0]


def test_or_high_freezes_after_the_window() -> None:
    h = Harness(**BASE)
    h.day(D1, rising(100, 20))
    h.day(D2, rising(121, 26))
    orh, orl = h.plot("or_high")[20:], h.plot("or_low")[20:]
    # day 2 bar i has high 122+i, low 120+i; the window is bars 1..24 (index 0..23)
    assert (
        orh[23] == 145.0 and orh[24] == 145.0 and orh[25] == 145.0
    )  # bars 25, 26 do not extend it
    assert orl == [120.0] * 26
    assert h.plot("day_len")[20:] == [
        float(i) for i in range(1, 27)
    ]  # resets to 1 on the new session
    assert h.plot("or_high")[0] == 101.0  # day 1 bar 1: set from the first bar's high


def test_htf_level_is_added_once_per_htf_bar_from_the_previous_completed_bar() -> None:
    # 30m HTF bars (6 five-minute bars each): highs 10 11 20 12 11 10.5, lows 9 8 7 6 5 4
    highs, lows = [10, 11, 20, 12, 11, 10.5], [9, 8, 7, 6, 5, 4]
    specs = [
        ((hi + lo) / 2, hi, lo, (hi + lo) / 2)
        for hi, lo in zip(highs, lows, strict=True)
        for _ in range(6)
    ]
    h = Harness(
        use_htf_levels=True, htf_pivot_len=2, swing_len=10, pivot_ties="strict", or_minutes=120
    )
    log: list[tuple[int, float, bool]] = []
    pool = h.engine.slots["pool"]
    real = pool.add_level  # type: ignore[attr-defined]
    core = h.engine.slots["core"]

    def spy(p: float, is_high: bool, atr: float, d: float) -> None:
        if p == p and p > 0:
            log.append((core.s.n_bars, p, is_high))  # type: ignore[attr-defined]
        real(p, is_high, atr, d)

    pool.add_level = spy  # type: ignore[attr-defined]
    h.day(D1, specs)
    # n=25: the opening range (20 high, 6 low; also HTF bar 4 starts but its pivot is not known yet);
    # n=31: HTF bar 5 starts: the pivot high of HTF bar 2 (20) is confirmed by bars 3 and 4 -> once
    assert log == [(25, 20.0, True), (25, 6.0, False), (31, 20.0, True)]


def test_htf_must_be_strictly_higher_than_the_chart() -> None:
    h = Harness(tf="15m", htf_mode="15m")
    with pytest.raises(ConfigError, match="HTF_NOT_HIGHER"):
        h.day(D1, [(100, 101, 99, 100)])
    Harness(tf="15m", htf_mode="30m").day(D1, [(100, 101, 99, 100)])  # fine
    Harness(tf="15m", htf_mode="15m", use_htf_levels=False).day(
        D1, [(100, 101, 99, 100)]
    )  # not used
