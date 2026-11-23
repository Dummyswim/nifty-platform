"""Job handlers: (connection, payload) -> result_ref. Raise on failure; never return empty."""

from collections.abc import Callable
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


HANDLERS: dict[str, Handler] = {"backtest": backtest, "engine_run": engine_run}
