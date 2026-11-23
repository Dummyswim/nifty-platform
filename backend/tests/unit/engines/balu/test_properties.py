"""D14 for steps 1-6 through the runner: batch == incremental == restart (JSON round trip)."""

from datetime import date
from typing import Any

import pytest

import nifty.engines.balu  # noqa: F401
from nifty.contracts import Instrument
from nifty.engines.runner import RunResult, run_batch, run_incremental, run_with_restart
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from tests.helpers import CAL, ORACLE

INST = Instrument(
    instrument_id="csv:NIFTY 50", provider="csv", tradingsymbol="NIFTY 50", tick_size=0.05
)
KW: dict[str, Any] = dict(instrument=INST, calendar=CAL, source_id="snap", allow_unready=True)


@pytest.fixture(scope="module")
def bars():  # type: ignore[no-untyped-def]
    ok, _ = validate_bars(parse_csv(ORACLE, instrument_id=INST.instrument_id), CAL)
    return [
        b
        for b in ok
        if date(2026, 10, 26) <= CAL.session_date(b.bar_start_utc) <= date(2026, 11, 3)
    ]


def view(r: RunResult) -> dict[str, object]:
    return {"plots": r.plots, "events": r.events, "overlays": r.overlays, "cfg": r.config_hash}


def test_batch_equals_incremental_and_restart(bars) -> None:  # type: ignore[no-untyped-def]
    batch = run_batch("pine.balu_zone", {}, bars, "5m", **KW)
    assert (
        len(batch.plots) > 400 and len(batch.overlays) > 100
    )  # zones, rails and markers are emitted
    assert any(o.kind == "zone" for o in batch.overlays) and any(
        o.id.startswith("kl:") for o in batch.overlays
    )
    assert view(run_incremental("pine.balu_zone", {}, bars, "5m", **KW)) == view(batch)
    for cut in (
        7,
        90,
        205,
        330,
    ):  # warm-up, mid-session, across the 100-bar flow window and a session boundary
        assert view(run_with_restart("pine.balu_zone", {}, bars, "5m", cut=cut, **KW)) == view(
            batch
        )


def test_all_documented_outputs_exist_and_not_ready_engine_stays_hidden(bars) -> None:  # type: ignore[no-untyped-def]
    from nifty.engines.base import EngineNotReady, get_engine, list_engines

    r = run_batch("pine.balu_zone", {}, bars[:2000], "5m", **KW)
    names = set(r.plots[-1][1])
    assert {"atr", "golden", "gold_state", "regime_idx", "cvd", "moving_line", "flow_z", "flow_state",
            "day_len", "or_high", "or_low", "pool_size", "next_up", "next_dn", "next_up_proj",
            "next_dn_proj", "loc_idx", "tap_demand_bot", "tap_supply_top", "zones_up", "zones_dn",
            "zones_size", "fp_n", "fp_tot", "fp_imb", "fp_valid", "press_buy", "press_sell",
            "sweep_d_conf", "sweep_s_conf"} <= names  # fmt: skip
    assert "pine.balu_zone" not in {e["id"] for e in list_engines()}
    with pytest.raises(EngineNotReady):
        get_engine("pine.balu_zone")


def test_ui_params_do_not_change_config_hash() -> None:
    from nifty.contracts import config_hash
    from nifty.engines.balu.params import BaluParams, BaluUi

    a = BaluParams.model_validate({})
    b = BaluParams.model_validate(
        {"ui": BaluUi(show_zones=False, color_gold="#000000", panel_pos="Bottom Left")}
    )
    c = BaluParams.model_validate({"show_div": False})  # gates a computed event: part of the hash
    assert config_hash("pine.balu_zone", "1", a) == config_hash("pine.balu_zone", "1", b)
    assert config_hash("pine.balu_zone", "1", a) != config_hash("pine.balu_zone", "1", c)
