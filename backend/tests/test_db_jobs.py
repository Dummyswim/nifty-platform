"""Job queue (D07): idempotent keys, SKIP LOCKED, stale requeue, failures stored, worker loop."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, create_engine, text

from nifty.db.jobs import claim_job, fail_job, finish_job, get_job, requeue_stale, submit_job
from nifty.worker import process_one
from nifty.worker.handlers import Handler
from tests.conftest import TABLES

pytestmark = pytest.mark.db


@pytest.fixture
def committed(migrated_url: str) -> Iterator[Engine]:
    """Real commits (SKIP LOCKED and the worker need them); nifty_test only, truncated around."""
    eng = create_engine(migrated_url)
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield eng
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    eng.dispose()


def test_same_key_returns_the_existing_job(db_conn: Connection) -> None:
    a, created = submit_job(db_conn, "backtest", {"x": 1, "y": [2]})
    b, again = submit_job(db_conn, "backtest", {"y": [2], "x": 1})  # key order is irrelevant
    assert (created, again, a == b) == (True, False, True)
    assert submit_job(db_conn, "engine_run", {"x": 1, "y": [2]})[0] != a  # kind is part of the key


def test_failure_is_stored_short_and_empty_result_is_not_success(db_conn: Connection) -> None:
    j, _ = submit_job(db_conn, "backtest", {"n": 1})
    fail_job(db_conn, j, "E: " + "x" * 1000)
    got = get_job(db_conn, j)
    assert got and got["status"] == "failed" and len(got["error"]) == 300
    k, _ = submit_job(db_conn, "backtest", {"n": 2})
    finish_job(db_conn, k, "")
    got = get_job(db_conn, k)
    assert got and got["status"] == "failed" and got["error"] == "handler returned no result"
    m, _ = submit_job(db_conn, "backtest", {"n": 3})
    finish_job(db_conn, m, "bt_1")
    got = get_job(db_conn, m)
    assert got and (got["status"], got["result_ref"], got["error"]) == ("done", "bt_1", None)


def test_stale_running_job_is_requeued_then_failed_after_max_attempts(db_conn: Connection) -> None:
    j, _ = submit_job(db_conn, "backtest", {"n": 9})
    assert claim_job(db_conn) is not None  # running, attempts 1
    assert requeue_stale(db_conn, 60) == 0  # fresh heartbeat
    db_conn.execute(
        text("UPDATE jobs SET heartbeat_at = now() - interval '5 minutes' WHERE id = :i"), {"i": j}
    )
    assert requeue_stale(db_conn, 60) == 1
    got = get_job(db_conn, j)
    assert got and got["status"] == "queued"
    for _ in range(2):  # attempts 2 and 3, each going stale
        assert claim_job(db_conn) is not None
        db_conn.execute(
            text("UPDATE jobs SET heartbeat_at = now() - interval '5 minutes' WHERE id = :i"),
            {"i": j},
        )
        requeue_stale(db_conn, 60, max_attempts=3)
    got = get_job(db_conn, j)
    assert got and got["status"] == "failed" and "stale" in got["error"]


def test_skip_locked_two_workers_never_take_the_same_job(committed: Engine) -> None:
    with committed.begin() as c:
        ids = [submit_job(c, "backtest", {"n": i})[0] for i in range(2)]
    a, b = committed.connect(), committed.connect()
    ta, tb = a.begin(), b.begin()
    try:
        ja, jb = claim_job(a), claim_job(b)  # a's row stays locked until commit
        assert ja is not None and jb is not None and ja["id"] != jb["id"]
        assert {ja["id"], jb["id"]} == set(ids)
        assert claim_job(b) is None  # nothing left to take, and it did not block on a's lock
    finally:
        ta.rollback()
        tb.rollback()
        a.close()
        b.close()


def test_worker_runs_handler_and_stores_failures(committed: Engine) -> None:
    def ok(conn: Connection, payload: dict[str, Any]) -> str:
        return f"ref-{payload['n']}"

    def boom(conn: Connection, payload: dict[str, Any]) -> str:
        raise RuntimeError("bad input " + "y" * 500)

    handlers: dict[str, Handler] = {"ok": ok, "boom": boom}
    with committed.begin() as c:
        a, _ = submit_job(c, "ok", {"n": 1})
        b, _ = submit_job(c, "boom", {"n": 2})
        u, _ = submit_job(c, "nokind", {"n": 3})
    assert [process_one(committed, handlers, 0.05) for _ in range(4)] == [True, True, True, False]
    with committed.connect() as c:
        ra, rb, ru = get_job(c, a), get_job(c, b), get_job(c, u)
    assert ra and (ra["status"], ra["result_ref"]) == ("done", "ref-1")
    assert (
        rb
        and rb["status"] == "failed"
        and rb["error"].startswith("RuntimeError: bad input")
        and len(rb["error"]) <= 300
    )
    assert ru and ru["status"] == "failed" and "no handler" in ru["error"]
