"""Tier-A parity of the C09 series against the TradingView golden export (docs/spec/04).

`fixtures/tv_golden/balu/ohlc_plots.csv` is exported once after C11 from a copy of the Pine script
with BALU_DEBUG_PLOTS.pine.txt appended; until then this skips and STATE lists "golden missing"."""

from pathlib import Path

import pytest

import nifty.engines.balu  # noqa: F401
from nifty.parity.cli import SERIES, run_parity

GOLDEN = Path(__file__).resolve().parents[5] / "fixtures" / "tv_golden" / "balu"


def test_tier_a_against_tradingview_when_the_golden_exists() -> None:
    if not (GOLDEN / "ohlc_plots.csv").exists():
        pytest.skip(
            "golden missing: fixtures/tv_golden/balu/ohlc_plots.csv (export after C11, RUNBOOK §Golden)"
        )
    lines, rc = run_parity("pine.balu_zone", golden=GOLDEN)
    assert rc == 0 and any("Tier A OK" in x for x in lines), "\n".join(lines)


def test_series_mapping_covers_every_debug_plot() -> None:
    names = {k for k in SERIES["pine.balu_zone"]}
    txt = (
        Path(__file__).resolve().parents[5] / "fixtures" / "tv_golden" / "BALU_DEBUG_PLOTS.pine.txt"
    ).read_text()
    for dbg in names:
        assert f'"{dbg}"' in txt, dbg  # the mapping and the Pine lines stay in sync
