"""Live option panes re-run engines on every finalized bar: superseded runs of the same option
contract + engine + params + timeframe are deleted so stored runs do not pile up."""

from typing import Literal

import pytest
from sqlalchemy import Connection, text

from nifty.contracts import Instrument
from nifty.db.bars import upsert_bars
from nifty.db.instruments import upsert_instrument
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from nifty.worker.handlers import engine_run
from tests.helpers import CAL, ORACLE

pytestmark = pytest.mark.db


def _seed(conn: Connection, iid: str, typ: Literal["INDEX", "CE", "PE"]) -> None:
    opt = typ != "INDEX"
    upsert_instrument(
        conn,
        Instrument(
            instrument_id=iid, provider="kite", tradingsymbol=iid.split(":")[-1], tick_size=0.05,
            instrument_type=typ, option_type=typ if typ != "INDEX" else None,
            underlying="NIFTY" if opt else None, strike=25000.0 if opt else None,
        ),
    )  # fmt: skip
    bars, _ = validate_bars(parse_csv(ORACLE, instrument_id=iid), CAL)
    upsert_bars(conn, bars[:-30])


def _grow(conn: Connection, iid: str) -> None:
    bars, _ = validate_bars(parse_csv(ORACLE, instrument_id=iid), CAL)
    upsert_bars(conn, bars[-30:])


def _runs(conn: Connection, iid: str) -> list[str]:
    return list(
        conn.execute(
            text("SELECT run_id FROM engine_runs WHERE instrument_id = :i"), {"i": iid}
        ).scalars()
    )


P = {"engine_id": "pine.nvs_scalper", "timeframe": "5m"}


def test_option_contract_keeps_only_the_latest_run(db_conn: Connection) -> None:
    iid = "kite:NFO:NIFTYTEST25000CE"
    _seed(db_conn, iid, "CE")
    first = engine_run(db_conn, {**P, "symbol": iid})
    _grow(db_conn, iid)
    second = engine_run(db_conn, {**P, "symbol": iid})
    assert second != first
    assert _runs(db_conn, iid) == [second]


def test_index_runs_are_kept(db_conn: Connection) -> None:
    iid = "kite:NSE:NIFTYTEST"
    _seed(db_conn, iid, "INDEX")
    first = engine_run(db_conn, {**P, "symbol": iid})
    _grow(db_conn, iid)
    second = engine_run(db_conn, {**P, "symbol": iid})
    assert sorted(_runs(db_conn, iid)) == sorted([first, second])


def test_a_run_used_by_a_backtest_is_never_deleted(db_conn: Connection) -> None:
    iid = "kite:NFO:NIFTYTEST25000PE"
    _seed(db_conn, iid, "PE")
    first = engine_run(db_conn, {**P, "symbol": iid})
    db_conn.execute(
        text(
            "INSERT INTO backtests (backtest_id, run_id, engine_id, instrument_id, snapshot_id, timeframe, "
            "mode, qty, cost_pts, params, summary) VALUES ('bt_x', :r, 'pine.nvs_scalper', :i, 'snap_x', '5m', "
            "'tv', 1, 0, '{}', '{}')"
        ),
        {"r": first, "i": iid},
    )
    _grow(db_conn, iid)
    engine_run(db_conn, {**P, "symbol": iid})
    assert first in _runs(db_conn, iid)
