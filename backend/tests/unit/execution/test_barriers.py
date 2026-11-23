"""resolve_barriers on hand-built bars (spec/03). B(o,h,l,c) is a tiny bar stand-in."""

from dataclasses import dataclass

import pytest

from nifty.execution import resolve_barriers


@dataclass(frozen=True)
class B:
    open: float
    high: float
    low: float
    close: float


def test_research_fixture_short_hits_stop_in_both_modes() -> None:
    # research §3 bar 2026-11-18 09:30; bearish entry at the open, target 25273.95, stop 25305.95
    b = B(25293.95, 25318.05, 25289.40, 25314.55)
    tv = resolve_barriers("short", 25293.95, 25305.95, 25273.95, [b], 10, "tv")
    assert (tv.exit_idx, tv.exit_px, tv.reason, tv.bars_held) == (0, 25305.95, "STOP", 1)
    assert tv.flags == ()
    # MAE clipped at the stop: 25305.95-25293.95 = 12.00 (not the bar high: 24.10)
    assert tv.mae_pts == pytest.approx(12.0)
    # tv path: (high-open)=24.10 >= (open-low)=4.55 -> O->L->H, so the 4.55 favourable move is real
    assert tv.mfe_pts == pytest.approx(4.55)
    cons = resolve_barriers("short", 25293.95, 25305.95, 25273.95, [b], 10, "conservative")
    assert (cons.exit_px, cons.reason, cons.flags) == (25305.95, "STOP", ())  # no ambiguity
    assert cons.mae_pts == pytest.approx(12.0)
    assert cons.mfe_pts == 0.0  # pessimistic: no credit for favourable moves on a stopped bar


def test_gap_through_stop_fills_at_open_long_and_short() -> None:
    r = resolve_barriers("long", 100, 95, 110, [B(100, 101, 99, 100), B(93, 94, 90, 91)], 10, "tv")
    assert (r.exit_idx, r.exit_px, r.reason) == (1, 93, "STOP") and "gap_through_stop" in r.flags
    assert r.mae_pts == 7 and r.mfe_pts == 1  # bar0 favourable 1; bar1 adverse clipped at the open
    s = resolve_barriers(
        "short", 100, 105, 90, [B(100, 101, 99, 100), B(107, 108, 106, 107)], 10, "conservative"
    )
    assert (s.exit_px, s.reason) == (107, "STOP") and s.mae_pts == 7


def test_gap_through_target_tv_improves_conservative_does_not() -> None:
    bars = [B(100, 101, 99, 100), B(112, 113, 111, 112)]
    tv = resolve_barriers("long", 100, 95, 110, bars, 10, "tv")
    cons = resolve_barriers("long", 100, 95, 110, bars, 10, "conservative")
    assert (tv.exit_px, tv.reason, tv.mfe_pts) == (112, "TARGET", 12)
    assert (cons.exit_px, cons.reason, cons.mfe_pts) == (110, "TARGET", 10)
    assert "gap_through_target" in tv.flags


def test_same_bar_both_barriers() -> None:
    # long: stop 98, target 103. (high-open)=3 < (open-low)=4 -> O->H->L: target first
    h_first = B(100, 103, 96, 101)
    r = resolve_barriers("long", 100, 98, 103, [h_first], 5, "tv")
    assert (r.reason, r.exit_px, r.mfe_pts, r.mae_pts, r.flags) == ("TARGET", 103, 3, 0, ())
    c = resolve_barriers("long", 100, 98, 103, [h_first], 5, "conservative")
    assert (c.reason, c.exit_px) == ("STOP", 98) and "ambiguous_bar" in c.flags
    # (high-open)=4 >= (open-low)=3 -> O->L->H: stop first
    l_first = B(100, 104, 97, 101)
    r2 = resolve_barriers("long", 100, 98, 103, [l_first], 5, "tv")
    assert (r2.reason, r2.exit_px, r2.mfe_pts, r2.mae_pts) == ("STOP", 98, 0, 2)
    # exact tie: falls to O->L->H and is logged as uncertain
    tie = B(100, 103, 97, 101)
    r3 = resolve_barriers("long", 100, 98, 103, [tie], 5, "tv")
    assert r3.reason == "STOP" and "uncertain_path" in r3.flags


def test_same_bar_both_short_mirror() -> None:
    # short: stop 102, target 97. (high-open)=2 < (open-low)=4 -> O->H->L: stop first
    r = resolve_barriers("short", 100, 102, 97, [B(100, 102, 96, 99)], 5, "tv")
    assert (r.reason, r.exit_px) == ("STOP", 102)
    # (high-open)=4 >= (open-low)=3 -> O->L->H: target first
    r2 = resolve_barriers("short", 100, 104, 97, [B(100, 104, 97, 99)], 5, "tv")
    assert (r2.reason, r2.exit_px) == ("TARGET", 97)


def test_timeout_counts_entry_bar_and_exits_at_close() -> None:
    bars = [B(100, 101, 99, 100.5), B(100.5, 101.5, 99.5, 101), B(101, 102, 100, 101.5)]
    r = resolve_barriers("long", 100, 90, 120, bars, 2, "conservative")
    assert (r.reason, r.exit_idx, r.exit_px, r.bars_held) == ("TIME", 1, 101, 2)
    assert r.mfe_pts == 1.5 and r.mae_pts == 1  # bar1: high 101.5 -> 1.5 ; bar0: low 99 -> 1


def test_data_ends_before_max_hold() -> None:
    r = resolve_barriers(
        "long", 100, 90, 120, [B(100, 101, 99, 100.5), B(100.5, 101, 100, 100.75)], 10, "tv"
    )
    assert (r.reason, r.exit_idx, r.exit_px) == ("TIME", 1, 100.75) and "data_ended" in r.flags


def test_exit_on_entry_bar_and_costs() -> None:
    r = resolve_barriers(
        "long", 100, 90, 103, [B(100, 104, 100, 103.5)], 5, "conservative", cost_pts=0.5
    )
    assert (r.exit_idx, r.reason, r.bars_held, r.exit_px) == (0, "TARGET", 1, 103)
    assert (r.gross_pts, r.cost_pts, r.net_pts) == (3, 0.5, 2.5)
    s = resolve_barriers(
        "short", 100, 110, 97, [B(100, 100.5, 96, 98)], 5, "conservative", cost_pts=1.0
    )
    assert (s.gross_pts, s.net_pts) == (3, 2.0)


def test_no_bars_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_barriers("long", 100, 90, 110, [], 5, "tv")
