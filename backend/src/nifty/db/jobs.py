"""Job queue (D07). Every function runs in the caller's transaction; the worker owns commits so a
claim (`FOR UPDATE SKIP LOCKED`) stays locked until it is committed."""

import hashlib
import json
from typing import Any

from sqlalchemy import Connection, text

MAX_ATTEMPTS = 3


def job_key(kind: str, payload: dict[str, Any]) -> str:
    raw = kind + "|" + json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def submit_job(conn: Connection, kind: str, payload: dict[str, Any]) -> tuple[int, bool]:
    """(job id, created). The same kind+payload returns the existing job (and its result); a
    failed one is requeued instead, so a request that failed before (e.g. no data yet) can run."""
    key = job_key(kind, payload)
    row = conn.execute(
        text(
            "INSERT INTO jobs (kind, key, payload) VALUES (:k, :key, CAST(:p AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET status = 'queued', attempts = 0, error = NULL, "
            "result_ref = NULL, started_at = NULL, finished_at = NULL, heartbeat_at = NULL "
            "WHERE jobs.status = 'failed' RETURNING id"
        ),
        {"k": kind, "key": key, "p": json.dumps(payload, default=str)},
    ).first()
    if row is not None:
        return int(row[0]), True
    return int(
        conn.execute(text("SELECT id FROM jobs WHERE key = :k"), {"k": key}).scalar_one()
    ), False


def claim_job(conn: Connection) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, started_at = now(), "
                "heartbeat_at = now(), error = NULL WHERE id = ("
                "  SELECT id FROM jobs WHERE status = 'queued' ORDER BY id "
                "  FOR UPDATE SKIP LOCKED LIMIT 1) "
                "RETURNING id, kind, payload, attempts"
            )
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def heartbeat(conn: Connection, job_id: int) -> None:
    conn.execute(text("UPDATE jobs SET heartbeat_at = now() WHERE id = :i"), {"i": job_id})


def finish_job(conn: Connection, job_id: int, result_ref: str | None) -> None:
    """Done needs a result; an empty result is a failure, never a silent success."""
    if not result_ref:
        fail_job(conn, job_id, "handler returned no result")
        return
    conn.execute(
        text(
            "UPDATE jobs SET status = 'done', result_ref = :r, error = NULL, finished_at = now() "
            "WHERE id = :i"
        ),
        {"r": result_ref, "i": job_id},
    )


def fail_job(conn: Connection, job_id: int, error: str) -> None:
    conn.execute(
        text("UPDATE jobs SET status = 'failed', error = :e, finished_at = now() WHERE id = :i"),
        {"e": (error or "unknown error")[:300], "i": job_id},
    )


def requeue_stale(conn: Connection, stale_seconds: float, max_attempts: int = MAX_ATTEMPTS) -> int:
    """Running jobs without a recent heartbeat go back to the queue; out of attempts => failed."""
    conn.execute(
        text(
            "UPDATE jobs SET status = 'failed', finished_at = now(), "
            "error = 'stale: heartbeat lost, attempts exhausted' "
            "WHERE status = 'running' AND attempts >= :m "
            "AND heartbeat_at < now() - make_interval(secs => :s)"
        ),
        {"m": max_attempts, "s": stale_seconds},
    )
    return conn.execute(
        text(
            "UPDATE jobs SET status = 'queued', started_at = NULL "
            "WHERE status = 'running' AND heartbeat_at < now() - make_interval(secs => :s)"
        ),
        {"s": stale_seconds},
    ).rowcount


def get_job(conn: Connection, job_id: int) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT id, kind, key, status, attempts, error, result_ref, created_at, "
                "started_at, finished_at FROM jobs WHERE id = :i"
            ),
            {"i": job_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)
