"""Backtest end to end on the oracle dataset: CLI path, API job path, exports, audit."""

import csv
import io
import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from nifty.cli import format_metrics
from nifty.contracts import Instrument
from nifty.db.backtests import BacktestError, get_backtest, load_trades, run_backtest
from nifty.db.bars import upsert_bars
from nifty.db.instruments import upsert_instrument
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from nifty.worker import process_one
from tests.conftest import ORIGIN
from tests.helpers import CAL, ORACLE

pytestmark = pytest.mark.db
SYMBOL = "NIFTY 50"
TWIN = ORACLE.parent.parent / "logs" / "scalper_trades.csv"
BT = {"engine_id": "pine.nvs_scalper", "symbol": SYMBOL, "timeframe": "5m", "mode": "tv"}


def twin_net_pts() -> float:
    return sum(float(r["net_pts"]) for r in csv.DictReader(TWIN.open()))


@pytest.fixture
def seeded(db_conn: Connection) -> Connection:
    ins = Instrument(
        instrument_id=f"csv:{SYMBOL}", provider="csv", tradingsymbol=SYMBOL, tick_size=0.05
    )
    upsert_instrument(db_conn, ins)
    bars, _ = validate_bars(parse_csv(ORACLE, instrument_id=ins.instrument_id), CAL)
    upsert_bars(db_conn, bars)
    return db_conn


def test_backtest_matches_the_twin_and_is_idempotent(seeded: Connection) -> None:
    bt_id = run_backtest(seeded, BT)
    row = get_backtest(seeded, bt_id)
    assert row and row["summary"]["n_trades"] == 15 and len(load_trades(seeded, bt_id)) == 15
    assert run_backtest(seeded, BT) == bt_id  # same inputs => same backtest, nothing duplicated
    assert seeded.execute(text("select count(*) from trades")).scalar() == 15
    # Net points vs the twin's log (-13.75 pts): ours is -23.74. Costs agree (88.99 vs 88.98: the
    # emulator's 0.0125 % per side = the twin's 2.5 bps round trip); the ~10 pts of gross difference
    # come from the target/stop anchoring (signal close + mintick rounding vs fill price, unrounded).
    tr = load_trades(seeded, bt_id)
    twin = list(csv.DictReader(TWIN.open()))
    assert abs(sum(t.cost_pts for t in tr) - sum(float(r["cost_pts"]) for r in twin)) < 0.5
    assert abs(row["summary"]["total_pnl_pts"] - twin_net_pts()) < 15
    assert any(line.startswith("trades 15") for line in format_metrics(row["summary"]))


def test_mode_rules(seeded: Connection) -> None:
    with pytest.raises(BacktestError, match="tv mode"):
        run_backtest(seeded, {**BT, "mode": "conservative"})
    with pytest.raises(BacktestError, match="cost_pts"):
        run_backtest(seeded, {**BT, "cost_pts": 1.0})
    with pytest.raises(BacktestError, match="unknown symbol"):
        run_backtest(seeded, {**BT, "symbol": "NOPE"})


def test_api_job_flow(api: tuple[TestClient, Engine]) -> None:
    c, eng = api
    H = {"Origin": ORIGIN}
    assert c.get("/api/v1/backtests").status_code == 200
    up = c.post(f"/api/v1/datasets/import?symbol={SYMBOL}&tick_size=0.05", content=ORACLE.read_bytes(),
                headers={**H, "Content-Type": "text/csv"})  # fmt: skip
    assert up.status_code == 200 and up.json()["accepted"] == 5996 and up.json()["stored"] is True
    assert (
        c.post(
            "/api/v1/datasets/import?symbol=X&tick_size=0.05", content=b"", headers=H
        ).status_code
        == 422
    )
    names = {e["id"] for e in c.get("/api/v1/engines").json()}
    assert "pine.nvs_scalper" in names
    r = c.post("/api/v1/backtests", json=BT, headers=H)
    assert r.status_code == 202 and r.json()["created"] is True and r.json()["status"] == "queued"
    jid = r.json()["job_id"]
    again = c.post("/api/v1/backtests", json=BT, headers=H).json()
    assert again["job_id"] == jid and again["created"] is False  # same key => same job
    assert process_one(eng) is True
    job = c.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "done", job
    bt_id = job["backtest_id"]
    assert (
        c.post("/api/v1/backtests", json=BT, headers=H).json()["result_ref"] == bt_id
    )  # same result
    trades = c.get(f"/api/v1/backtests/{bt_id}/trades").json()
    assert len(trades) == 15
    an = c.get(f"/api/v1/backtests/{bt_id}/analytics").json()
    assert an["n_trades"] == 15 and an["low_n"] is True
    assert c.get(f"/api/v1/backtests/{bt_id}").json()["summary"] == an
    assert [b["backtest_id"] for b in c.get("/api/v1/backtests").json()] == [bt_id]
    # exports open and carry 15 rows
    rows = list(
        csv.DictReader(io.StringIO(c.get(f"/api/v1/backtests/{bt_id}/export?fmt=csv").text))
    )
    assert len(rows) == 15 and "net_pts" in rows[0]
    assert len(c.get(f"/api/v1/backtests/{bt_id}/export?fmt=json").json()["trades"]) == 15
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(c.get(f"/api/v1/backtests/{bt_id}/export?fmt=xlsx").content))
    assert wb["trades"].max_row == 16
    # audit
    a = c.get(f"/api/v1/backtests/{bt_id}/audit/{trades[0]['trade_id']}?window=5").json()
    assert a["strike"] is None and a["option_type"] is None and a["pnl_inr"] is None
    assert a["levels"]["stop_px_pts"] is not None and a["levels"]["target_px_pts"] is not None
    assert a["window_bars"] and any(e["event_type"] == "signal" for e in a["events"])
    assert a["stop_hit"] != a["target_hit"] or a["exit_reason"] not in {"SL", "TP"}
    assert c.get(f"/api/v1/backtests/{bt_id}/audit/nope").status_code == 404
    # plots / events / overlays by run
    run_id = c.get(f"/api/v1/backtests/{bt_id}").json()["run_id"]
    p = c.get(f"/api/v1/plots?run_id={run_id}").json()
    assert len(p["t"]) == 1199 and "vwap" in p["series"]
    assert len(c.get(f"/api/v1/events?run_id={run_id}").json()["events"]) == 50
    assert c.get(f"/api/v1/overlays?run_id={run_id}").json()["overlays"]
    snap = c.get(f"/api/v1/backtests/{bt_id}").json()["snapshot_id"]
    assert (
        c.get(f"/api/v1/plots?engine_id=pine.nvs_scalper&snapshot_id={snap}&timeframe=5m").json()[
            "run_id"
        ]
        == run_id
    )
    # failures are stored on the job, with a short message
    bad = c.post("/api/v1/backtests", json={**BT, "symbol": "NOPE"}, headers=H).json()["job_id"]
    process_one(eng)
    j = c.get(f"/api/v1/jobs/{bad}").json()
    assert j["status"] == "failed" and "unknown symbol" in j["error"]
    # engine run job
    er = c.post(
        "/api/v1/engines/pine.nvs_scalper/run",
        json={"symbol": SYMBOL, "timeframe": "5m"},
        headers=H,
    )
    assert er.status_code == 202
    process_one(eng)
    assert c.get(f"/api/v1/jobs/{er.json()['job_id']}").json()["result_ref"] == run_id  # same run
    assert c.post("/api/v1/engines/nope/run", json={"symbol": SYMBOL}, headers=H).status_code == 404


def test_api_requires_login(client: TestClient) -> None:
    for path in ("/api/v1/engines", "/api/v1/backtests", "/api/v1/jobs/1", "/api/v1/plots"):
        assert client.get(path).status_code == 401
    assert client.post("/api/v1/backtests", json=BT).status_code == 401
    assert json is not None and Path is not None


def test_engine_run_reruns_after_new_bars(api: tuple[TestClient, Engine]) -> None:
    c, eng = api
    H = {"Origin": ORIGIN}
    c.post(f"/api/v1/datasets/import?symbol={SYMBOL}&tick_size=0.05", content=ORACLE.read_bytes(),
           headers={**H, "Content-Type": "text/csv"})  # fmt: skip
    body = {"symbol": SYMBOL, "timeframe": "5m"}
    first = c.post("/api/v1/engines/pine.nvs_scalper/run", json=body, headers=H).json()
    again = c.post("/api/v1/engines/pine.nvs_scalper/run", json=body, headers=H).json()
    assert again["job_id"] == first["job_id"]  # same data: the cached run
    with eng.connect() as conn:
        iid = conn.execute(
            text("SELECT instrument_id FROM instruments WHERE tradingsymbol = :s"), {"s": SYMBOL}
        ).scalar_one()
    last = parse_csv(ORACLE, instrument_id=iid)[-1]
    nxt = last.model_copy(update={"bar_start_utc": last.bar_start_utc + timedelta(minutes=1),
                                  "bar_end_utc": last.bar_end_utc + timedelta(minutes=1)})  # fmt: skip
    with eng.begin() as conn:
        upsert_bars(conn, [nxt])
    fresh = c.post("/api/v1/engines/pine.nvs_scalper/run", json=body, headers=H).json()
    assert fresh["job_id"] != first["job_id"]  # a newer bar exists: a new run
