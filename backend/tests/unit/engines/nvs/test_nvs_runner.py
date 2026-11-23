"""D14 properties and oracle parity for pine.nvs_scalper through the runner."""

from datetime import date
from typing import Any

import pytest

from nifty.contracts import Instrument
from nifty.engines.base import get_engine
from nifty.engines.runner import RunResult, run_batch, run_incremental, run_with_restart
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from nifty.parity.compare import tier_bc
from nifty.parity.tv_io import load_oracle_trades
from tests.helpers import CAL, ORACLE

INST = Instrument(
    instrument_id="csv:NIFTY 50", provider="csv", tradingsymbol="NIFTY 50", tick_size=0.05
)
TRADES = ORACLE.parent.parent / "logs" / "scalper_trades.csv"


@pytest.fixture(scope="module")
def bars():  # type: ignore[no-untyped-def]
    ok, _ = validate_bars(parse_csv(ORACLE, instrument_id=INST.instrument_id), CAL)
    return ok


def view(r: RunResult) -> dict[str, object]:
    return {
        "bars": r.bars, "plots": r.plots, "events": r.events, "overlays": r.overlays,
        "trades": r.trades, "panel": r.panel, "cfg": r.config_hash,
    }  # fmt: skip


def test_registered_and_ready() -> None:
    import nifty.engines.nvs  # noqa: F401

    assert get_engine("pine.nvs_scalper").ready


def test_batch_equals_incremental_and_restart(bars) -> None:  # type: ignore[no-untyped-def]
    # sessions 10-27 .. 11-02 hold four trades (TP, BE_STOP, BE_STOP, SL, SL, EOD)
    sub = [
        b
        for b in bars
        if date(2026, 10, 27) <= CAL.session_date(b.bar_start_utc) <= date(2026, 11, 2)
    ]
    kw: dict[str, Any] = dict(instrument=INST, calendar=CAL, source_id="snap_t")
    batch = run_batch("pine.nvs_scalper", {}, sub, "5m", **kw)
    assert len(batch.trades) >= 4
    assert view(run_incremental("pine.nvs_scalper", {}, sub, "5m", **kw)) == view(batch)
    for cut in (10, 120, 201):  # before, during and after trades
        assert view(run_with_restart("pine.nvs_scalper", {}, sub, "5m", cut=cut, **kw)) == view(
            batch
        )
    prov = run_incremental("pine.nvs_scalper", {}, sub, "5m", provisional=True, **kw)
    assert view(prov) == view(batch)  # provisional updates never touch confirmed state
    assert prov.provisional
    # Pine L278 barstate.isconfirmed: a forming bar never produces an entry signal
    assert not [e for p in prov.provisional for e in p["events"] if e.event_type == "signal"]


def test_oracle_parity(bars) -> None:  # type: ignore[no-untyped-def]
    r = run_batch("pine.nvs_scalper", {}, bars, "5m", instrument=INST, calendar=CAL)
    res = tier_bc(r.trades, load_oracle_trades(TRADES))
    assert (res.n_ours, res.entries_ok) == (15, 15)
    assert res.exits_ok >= 14
    # only documented diff: the twin re-anchors the target to the fill, so 11-03 TP fires 2 bars sooner
    assert len(res.diffs) == 1 and res.diffs[0].startswith("exit 11-03 12:30")
    assert all(
        0 <= (e.available_at_utc - e.bar_start_utc).total_seconds() / 60 <= 5 for e in r.events
    )


def test_prefix_immunity(bars) -> None:  # type: ignore[no-untyped-def]
    """D14: results on a prefix equal the same prefix of the full run (no lookahead)."""
    full = run_batch("pine.nvs_scalper", {}, bars, "5m", instrument=INST, calendar=CAL)
    cut = full.bars[700].bar_end_utc  # mid-session, between trades
    pre = run_batch(
        "pine.nvs_scalper", {}, [b for b in bars if b.bar_start_utc < cut], "5m",
        instrument=INST, calendar=CAL,
    )  # fmt: skip
    n = len(pre.bars)
    assert n == 701 and pre.plots == full.plots[:n]
    assert pre.events == [e for e in full.events if e.bar_end_utc <= cut]
    assert pre.trades == [t for t in full.trades if t.exit_time <= cut]
    assert [o for o in pre.overlays] == [o for o in full.overlays if (o.avail_at_utc or cut) <= cut]
