"""Job handlers: (connection, payload) -> result_ref. Raise on failure; never return empty."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection

from nifty.db.backtests import BacktestError, resolve_input, run_backtest
from nifty.db.runs import persist_run
from nifty.engines.base import get_engine, load_builtin_engines
from nifty.engines.runner import run_batch
from nifty.timeutil import Calendar

Handler = Callable[[Connection, dict[str, Any]], str]


def backtest(conn: Connection, payload: dict[str, Any]) -> str:
    return run_backtest(conn, payload)


def engine_run(conn: Connection, payload: dict[str, Any]) -> str:
    """Run an engine over a snapshot and persist plots/events/overlays; result = run_id."""
    load_builtin_engines()
    cal = Calendar.load()
    ins, bars, snapshot_id = resolve_input(conn, payload, cal)
    try:
        spec = get_engine(payload["engine_id"])
    except KeyError as e:
        raise BacktestError(f"unknown engine {payload['engine_id']!r}") from e
    r = run_batch(
        payload["engine_id"], payload.get("params") or {}, bars,
        payload.get("timeframe") or spec.cls.default_timeframe,
        instrument=ins, calendar=cal, source_id=snapshot_id,
    )  # fmt: skip
    return persist_run(conn, r)[0]


def kite_instruments(conn: Connection, payload: dict[str, Any]) -> str:
    """Download the daily instrument dump, store it as a version and upsert what we use."""
    from nifty.config import get_settings
    from nifty.db.kite import client_for, save_master

    text = client_for(conn, get_settings()).instruments()
    version, ins = save_master(conn, text)
    return f"{version} ({len(ins)} instruments)"


def kite_backfill(conn: Connection, payload: dict[str, Any]) -> str:
    """Fetch historical 1m candles for a stored Kite instrument and store them (D08)."""
    from nifty.config import get_settings
    from nifty.db.bars import upsert_bars
    from nifty.db.instruments import find_by_symbol
    from nifty.db.kite import client_for
    from nifty.marketdata.kite.provider import KiteProvider
    from nifty.marketdata.validation import validate_bars
    from nifty.timeutil import IST

    ins = find_by_symbol(conn, payload["symbol"], provider="kite")
    if ins is None:
        raise BacktestError(
            f"{payload['symbol']!r} is not in the Kite instrument master; refresh instruments"
        )
    cal = Calendar.load()
    day0 = datetime.fromisoformat(payload["from_date"]).replace(tzinfo=IST)
    day1 = datetime.fromisoformat(payload["to_date"]).replace(tzinfo=IST) + timedelta(days=1)
    bars = list(KiteProvider(client_for(conn, get_settings())).historical(ins, "1m", day0, day1))
    ok, report = validate_bars(bars, cal)
    u = upsert_bars(conn, ok)
    return (
        f"{len(ok)} bars: inserted {u.inserted}, revised {u.revised}, unchanged {u.noop}; "
        f"gaps {len(report.gaps)}"
    )


HANDLERS: dict[str, Handler] = {
    "backtest": backtest,
    "engine_run": engine_run,
    "kite_instruments": kite_instruments,
    "kite_backfill": kite_backfill,
}
