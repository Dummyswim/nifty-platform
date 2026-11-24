"""Options API on a seeded nifty_test with the SYNTHETIC fixture, and the paper backtest."""

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.conftest import ORIGIN
from tests.helpers import ORACLE

pytestmark = pytest.mark.db
H = {"Origin": ORIGIN}
FIX = Path(__file__).resolve().parents[2] / "fixtures" / "options_demo" / "build.py"


def demo() -> Any:
    spec = importlib.util.spec_from_file_location("options_demo_build", FIX)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def seeded(api: tuple[TestClient, Engine]) -> tuple[TestClient, Engine, dict[str, object]]:
    c, eng = api
    with eng.begin() as conn:
        info = demo().seed(conn)
    return c, eng, info


def test_expiries_kinds_come_from_the_listed_contracts(seeded: Any) -> None:
    c, _, info = seeded
    r = c.get("/api/v1/options/expiries").json()
    exps = [date.fromisoformat(x) for x in r["expiries"]]
    assert exps == info["expiries"] and r["step"] == 50.0
    assert (
        r["kinds"]["current weekly"] == exps[0].isoformat()
        and r["kinds"]["next weekly"] == exps[1].isoformat()
    )
    assert r["kinds"]["monthly"] is not None
    assert c.get("/api/v1/options/expiries", params={"underlying": "BANKNIFTY"}).json()[
        "kinds"
    ] == {
        "current weekly": None,
        "next weekly": None,
        "monthly": None,
    }  # a kind that is not listed is unavailable, never guessed


def test_chain_shows_atm_neighbours_recorded_quotes_and_honest_greeks_states(seeded: Any) -> None:
    c, _, info = seeded
    e0, e2 = info["expiries"][0].isoformat(), info["expiries"][2].isoformat()
    ch = c.get("/api/v1/options/chain", params={"expiry": e0, "width": 3}).json()
    assert (
        ch["spot"] == 25_020.0
        and ch["atm"] == 25_000.0
        and ch["step"] == 50.0
        and ch["r_set"] is False
    )
    assert [r["strike"] for r in ch["rows"]] == [
        24_850.0 + 50 * i for i in range(7)
    ]  # ATM +- 3 steps
    assert [r["strike"] for r in ch["rows"] if r["atm"]] == [25_000.0]
    row = next(r for r in ch["rows"] if r["atm"])
    ce = row["ce"]
    assert (
        ce["recorded"]
        and ce["last"]
        and ce["bid"] == pytest.approx(ce["last"] - 0.5)
        and ce["ask"] == pytest.approx(ce["last"] + 0.5)
    )
    assert ce["oi"] == 1_020.0 and 0 <= ce["age_s"] < 30  # the last tick, 5 s old when seeded
    assert (
        ce["greeks"] == "n/a" and ce["greeks_note"] == "Greeks n/a: set r in Settings"
    )  # r has no default
    assert (
        ch["picks"]["ITM"] == {"CE": 24_900.0, "PE": 25_100.0}
        and ch["picks"]["Deep OTM"]["CE"] == 25_250.0
    )
    far = c.get(
        "/api/v1/options/chain", params={"expiry": e2, "width": 1}
    ).json()  # listed, never recorded
    assert (
        far["rows"][0]["ce"]["recorded"] is False
        and far["rows"][0]["ce"]["greeks_note"] == "not recorded"
    )
    assert c.get("/api/v1/options/chain", params={"expiry": "2030-01-01"}).status_code == 404
    # with r set the Greeks are computed and labelled so; IV round-trips through the model
    assert c.put("/api/v1/prefs/options.r", json={"value": 0.065}, headers=H).status_code == 200
    ch2 = c.get("/api/v1/options/chain", params={"expiry": e0, "width": 3}).json()
    ce2 = next(r for r in ch2["rows"] if r["atm"])["ce"]
    assert ch2["r_set"] and ce2["greeks"] == "computed" and 0 < ce2["delta"] < 1 and ce2["iv"] > 0
    assert "computed" in ce2["greeks_note"] and ce2["theta_day"] < 0 and ce2["gamma"] > 0


def test_contract_bars_have_volume_oi_and_coverage_flags(seeded: Any) -> None:
    c, _, info = seeded
    e0 = f"{info['expiries'][0]:%y%m%d}"
    cid = f"kite:NFO:NIFTYDEMO{e0}25000CE"
    r = c.get("/api/v1/options/contract-bars", params={"contract_id": cid}).json()
    assert (
        r["coverage"]["recorded"] and r["coverage"]["n_bars"] == 3 and r["coverage"]["n_ticks"] == 3
    )
    assert len(r["bars"]["t"]) == 3 and r["bars"]["v"] == [100.0, 200.0, 300.0]
    assert len(r["oi"]["t"]) == 3 and r["oi"]["v"][-1] == 1_020.0
    none = c.get(
        "/api/v1/options/contract-bars", params={"contract_id": f"kite:NFO:NIFTYDEMO{e0}25300PE"}
    ).json()
    assert (
        none["bars"] is None
        and none["coverage"]["recorded"] is True
        and none["coverage"]["n_bars"] == 0
    )  # ticks only
    unseen = f"kite:NFO:NIFTYDEMO{info['expiries'][3]:%y%m%d}25000CE"
    u = c.get("/api/v1/options/contract-bars", params={"contract_id": unseen}).json()
    assert (
        u["coverage"]["recorded"] is False and u["bars"] is None and u["oi"] == {"t": [], "v": []}
    )
    assert c.get("/api/v1/options/contract-bars", params={"contract_id": "nope"}).status_code == 404


def test_option_routes_need_login(client: TestClient) -> None:
    for p in ("/expiries", "/chain?expiry=2030-01-01", "/contract-bars?contract_id=x"):
        assert client.get("/api/v1/options" + p).status_code == 401


def test_backtest_option_policy_maps_recorded_quotes_and_counts_no_quote(seeded: Any) -> None:
    """The NVS trades of the oracle run have no recorded option quotes (the fixture is 'now'): every
    one is skipped as no_quote (D12: nothing is reconstructed), and the index result is untouched."""
    from nifty.contracts import Instrument
    from nifty.db.backtests import run_backtest
    from nifty.db.bars import upsert_bars
    from nifty.db.instruments import upsert_instrument
    from nifty.marketdata.importer import parse_csv
    from nifty.marketdata.validation import validate_bars
    from tests.helpers import CAL

    _, eng, _ = seeded
    ins = Instrument(
        instrument_id="csv:NIFTY 50", provider="csv", tradingsymbol="NIFTY 50", tick_size=0.05
    )
    with eng.begin() as conn:
        upsert_instrument(conn, ins)
        upsert_bars(conn, validate_bars(parse_csv(ORACLE, instrument_id=ins.instrument_id), CAL)[0])
        bt = {
            "engine_id": "pine.nvs_scalper",
            "symbol": "csv:NIFTY 50",
            "timeframe": "5m",
            "mode": "tv",
        }
        plain = run_backtest(conn, bt)
        opt = run_backtest(
            conn,
            {
                **bt,
                "option_policy": {"strike_type": "ATM", "expiry_kind": "current weekly", "lots": 1},
            },
        )
        assert plain != opt  # the policy is part of the identity
        rows = conn.execute(text("select backtest_id, summary from backtests")).all()
    summ = {r[0]: r[1] for r in rows}
    assert summ[plain]["option"] is None and summ[plain]["n_trades"] == 15
    o = summ[opt]["option"]
    assert (
        summ[opt]["n_trades"] == 15 and summ[opt]["total_pnl_pts"] == summ[plain]["total_pnl_pts"]
    )
    assert (
        o["n_mapped"] == 0 and o["no_quote"] + o["no_contract"] == 15 and o["total_pnl_inr"] == 0.0
    )
    assert o["policy"]["strike_type"] == "ATM"
    _ = (UTC, datetime)
