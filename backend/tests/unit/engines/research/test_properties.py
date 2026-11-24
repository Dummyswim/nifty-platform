"""D14 through the runner on the oracle 1m data: batch == incremental == restart, and a run on a
prefix equals the same prefix of the full run (no future-bar influence)."""

from datetime import date
from typing import Any

import pytest

import nifty.engines.research  # noqa: F401
from nifty.contracts import Instrument
from nifty.engines.runner import RunResult, run_batch, run_incremental, run_with_restart
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from tests.helpers import CAL, ORACLE

ID = "research.distance_entry_v1"
INST = Instrument(
    instrument_id="csv:NIFTY 50", provider="csv", tradingsymbol="NIFTY 50", tick_size=0.05
)
KW: dict[str, Any] = dict(instrument=INST, calendar=CAL, source_id="snap")
BASELINES = [
    "anchor_cross_ema_order",
    "ema_gap_reexpansion",
    "ema_aligned_gap_reexpansion",
    "armed_resumption",
]


@pytest.fixture(scope="module")
def bars():  # type: ignore[no-untyped-def]
    ok, _ = validate_bars(parse_csv(ORACLE, instrument_id=INST.instrument_id), CAL)
    return [
        b
        for b in ok
        if date(2026, 10, 26) <= CAL.session_date(b.bar_start_utc) <= date(2026, 11, 3)
    ]


def view(r: RunResult) -> dict[str, object]:
    return {
        "plots": r.plots,
        "events": r.events,
        "trades": r.trades,
        "panel": r.panel,
        "cfg": r.config_hash,
    }


@pytest.mark.parametrize("baseline", BASELINES)
def test_batch_equals_incremental_and_restart(bars, baseline: str) -> None:  # type: ignore[no-untyped-def]
    prm = {"baseline": baseline}
    batch = run_batch(ID, prm, bars, "1m", **KW)
    assert len(batch.plots) == len(bars) and batch.panel is not None
    assert view(run_incremental(ID, prm, bars, "1m", **KW)) == view(batch)
    for cut in (
        50,
        700,
        1900,
        3200,
    ):  # warm-up, mid-session, across sessions, with open positions/setups
        assert view(run_with_restart(ID, prm, bars, "1m", cut=cut, **KW)) == view(batch), cut


@pytest.mark.parametrize("baseline", BASELINES)
def test_future_bars_do_not_change_the_past(bars, baseline: str) -> None:  # type: ignore[no-untyped-def]
    prm = {"baseline": baseline}
    full = run_batch(ID, prm, bars, "1m", **KW)
    cut_i = 2500
    cut = full.bars[cut_i].bar_end_utc
    pre = run_batch(ID, prm, [b for b in bars if b.bar_start_utc < cut], "1m", **KW)
    assert pre.plots == full.plots[: cut_i + 1]
    assert pre.events == [e for e in full.events if e.bar_end_utc <= cut]
    assert pre.trades == [t for t in full.trades if t.exit_time <= cut]


def test_engine_is_registered_ready_and_the_panel_lists_the_diagnostics(bars) -> None:  # type: ignore[no-untyped-def]
    from nifty.engines.base import get_engine, list_engines

    assert get_engine(ID).ready and ID in {e["id"] for e in list_engines()}
    r = run_batch(ID, {}, bars[:800], "1m", **KW)
    assert r.panel is not None
    assert [x["label"] for x in r.panel["rows"]][:3] == ["Baseline", "State", "D (P-V)/A"]
    anchor = [x["value"] for x in r.panel["rows"] if x["label"] == "Anchor"]
    assert anchor == ["TWAP / equal-bar session average"]  # index spot has no volume: labelled TWAP


def test_event_vocabulary_and_outcomes_on_the_oracle(bars) -> None:  # type: ignore[no-untyped-def]
    r = run_batch(ID, {"baseline": "armed_resumption"}, bars, "1m", **KW)
    kinds = {e.event_type for e in r.events}
    assert kinds <= {
        "research.watch",
        "research.armed",
        "research.entry",
        "research.exit",
        "research.invalidated",
    }
    assert {"research.watch", "research.armed", "research.entry", "research.exit"} <= kinds
    assert {t.exit_reason for t in r.trades} <= {"TARGET_FIRST", "STOP_FIRST", "TIME_EXIT"}
    assert all(t.execution_mode == "conservative" and t.engine_id == ID for t in r.trades)
    assert all(
        t.entry_time > t.signal_bar_start for t in r.trades if t.signal_bar_start
    )  # fill after the signal bar
