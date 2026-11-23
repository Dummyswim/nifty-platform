"""LevelPool (Pine f_addLevel / f_prunePool / f_nearestAbove / f_nearestBelow, L232-307)."""

import math

import pytest

from nifty.engines.balu.levels import LevelPool


def pool(*items: tuple[float, bool], atr: float = 1.0, dedupe: float = 0.5) -> LevelPool:
    p = LevelPool()
    for price, hi in items:
        p.add_level(price, hi, atr, dedupe)
    return p


def test_merge_is_a_plain_average_within_atr_times_dedupe_and_same_flag_only() -> None:
    p = pool((100.0, True), (100.4, True))  # tol = 1.0 * 0.5
    assert p.prices == [100.2] and p.is_high == [True]
    p.add_level(100.4, False, 1.0, 0.5)  # a low never merges into a high
    assert p.prices == [100.2, 100.4] and p.is_high == [True, False]
    p.add_level(100.7, True, 1.0, 0.5)  # |100.2 - 100.7| = 0.5 <= tol: boundary inclusive
    assert p.prices[0] == pytest.approx(100.45)


def test_merge_hits_the_first_matching_entry_in_order() -> None:
    p = pool((100.0, True), (100.6, True))  # 0.6 > tol: two levels
    assert len(p) == 2
    p.add_level(100.3, True, 1.0, 0.5)  # within tol of BOTH; the first one wins
    assert p.prices == [pytest.approx(100.15), 100.6]


def test_invalid_levels_and_atr_are_skipped() -> None:
    p = LevelPool()
    for price, atr in [(math.nan, 1.0), (0.0, 1.0), (-5.0, 1.0), (100.0, math.nan), (100.0, 0.0)]:
        p.add_level(price, True, atr, 0.5)
    assert len(p) == 0


def test_prune_removes_far_levels_scanning_from_the_end() -> None:
    p = LevelPool()
    p.prices, p.is_high = [10.0, 50.0, 11.0, 90.0], [True, False, True, False]
    p.prune(close=50.0, atr=1.0, prune_atr=14.0)  # far = 14: only 50 survives
    assert p.prices == [50.0] and p.is_high == [False]  # flags stay aligned
    q = LevelPool()
    q.prices, q.is_high = [40.0, 45.0, 55.0, 70.0, 49.0], [True, False, True, False, True]
    q.prune(close=50.0, atr=1.0, prune_atr=10.0)  # 40 is exactly 10 away: kept; 70 removed
    assert q.prices == [40.0, 45.0, 55.0, 49.0] and q.is_high == [True, False, True, True]


def test_cap_of_60_drops_the_oldest() -> None:
    p = LevelPool()
    for v in range(1, 71):  # spacing 1 >> tol 0.05
        p.add_level(float(v), True, 1.0, 0.05)
    assert len(p) == 70
    p.prune(close=35.0, atr=1.0, prune_atr=60.0)
    assert len(p) == 60 and p.prices[0] == 11.0 and p.prices[-1] == 70.0


def test_nearest_above_and_below_are_strict_and_skip_used_prices() -> None:
    p = pool((100.0, True), (102.0, False), (105.0, True), (101.0, False), atr=1.0, dedupe=0.05)
    assert p.nearest_above(100.0, 0.5, [], 1.0) == 101.0  # lowest level > 100.5; flags ignored
    assert p.nearest_above(100.0, 0.5, [101.0], 0.5) == 102.0  # 101 is taken
    assert p.nearest_above(100.0, 2.0, [], 0.0) == 105.0  # 102 == ref+gap is NOT > ref+gap
    assert p.nearest_below(102.0, 0.5, [], 1.0) == 101.0
    assert p.nearest_below(102.0, 1.0, [], 0.0) == 100.0  # 101 == ref-gap is excluded
    assert math.isnan(p.nearest_above(200.0, 0.0, [], 0.0))
    assert p.nearest_above(100.0, 0.0, [102.0, 101.0, 105.0], 5.0) != p.nearest_above(
        100.0, 0.0, [], 5.0
    )
