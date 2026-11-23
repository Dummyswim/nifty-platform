"""Engine run persistence (D07). Same (engine, version, config_hash, snapshot_id, timeframe)
returns the existing run and writes nothing. Trades are persisted with backtests (C04)."""

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from nifty.contracts import EngineEvent, OverlayElement
from nifty.engines.runner import RunResult


def run_key(r: RunResult) -> str:
    raw = "|".join([r.engine_id, r.engine_version, r.config_hash, r.source_id, r.timeframe])
    return hashlib.sha256(raw.encode()).hexdigest()


def _j(obj: Any) -> str:
    return json.dumps(obj, default=str, allow_nan=False)


def find_run(conn: Connection, r: RunResult) -> str | None:
    row = conn.execute(
        text("SELECT run_id FROM engine_runs WHERE run_key = :k"), {"k": run_key(r)}
    ).first()
    return None if row is None else str(row[0])


def persist_run(conn: Connection, r: RunResult) -> tuple[str, bool]:
    """Return (run_id, created). Runs in the caller's transaction."""
    key = run_key(r)
    run_id = "run_" + key[:16]
    got = conn.execute(
        text(
            "INSERT INTO engine_runs (run_id, run_key, engine_id, engine_version, config_hash, "
            "instrument_id, timeframe, source_id, n_bars, panel) VALUES (:id, :k, :e, :v, :c, "
            ":i, :tf, :s, :n, CAST(:panel AS jsonb)) ON CONFLICT (run_key) DO NOTHING RETURNING run_id"
        ),
        {
            "id": run_id, "k": key, "e": r.engine_id, "v": r.engine_version, "c": r.config_hash,
            "i": r.instrument_id, "tf": r.timeframe, "s": r.source_id, "n": len(r.bars),
            "panel": _j(r.panel),
        },
    ).first()  # fmt: skip
    if got is None:
        existing = find_run(conn, r)
        assert existing is not None
        return existing, False
    conn.execute(
        text(
            "INSERT INTO engine_configs (config_hash, engine_id, engine_version, params) "
            "VALUES (:c, :e, :v, CAST(:p AS jsonb)) ON CONFLICT DO NOTHING"
        ),
        {"c": r.config_hash, "e": r.engine_id, "v": r.engine_version, "p": _j(r.params)},
    )
    if r.plots:
        conn.execute(
            text(
                "INSERT INTO plot_points (run_id, bar_start_utc, values) "
                "VALUES (:r, :t, CAST(:v AS jsonb))"
            ),
            [{"r": run_id, "t": t, "v": _j(v)} for t, v in r.plots],
        )
    if r.events:
        conn.execute(
            text(
                "INSERT INTO events (run_id, ord, event_id, event_type, bar_start_utc, available_at_utc, "
                "confirmed_or_provisional, envelope) VALUES (:r, :o, :id, :ty, :bs, :av, :cp, "
                "CAST(:env AS jsonb))"
            ),
            [
                {
                    "r": run_id, "o": i, "id": str(e.event_id), "ty": e.event_type, "bs": e.bar_start_utc,
                    "av": e.available_at_utc, "cp": e.confirmed_or_provisional,
                    "env": e.model_dump_json(),
                }
                for i, e in enumerate(r.events)
            ],
        )  # fmt: skip
    if r.overlays:
        conn.execute(
            text(
                "INSERT INTO overlay_elements (run_id, ord, id, ver, avail_at_utc, deleted, element) "
                "VALUES (:r, :o, :id, :ver, :av, :d, CAST(:el AS jsonb)) ON CONFLICT DO NOTHING"
            ),
            [
                {
                    "r": run_id, "o": i, "id": o.id, "ver": o.ver, "av": o.avail_at_utc, "d": o.deleted,
                    "el": o.model_dump_json(),
                }
                for i, o in enumerate(r.overlays)
            ],
        )  # fmt: skip
    return run_id, True


def load_plots(conn: Connection, run_id: str) -> list[tuple[datetime, dict[str, float | None]]]:
    rows = conn.execute(
        text(
            "SELECT bar_start_utc, values FROM plot_points WHERE run_id = :r ORDER BY bar_start_utc"
        ),
        {"r": run_id},
    )
    return [(r[0], r[1]) for r in rows]


def load_events(
    conn: Connection, run_id: str, available_by: datetime | None = None
) -> list[EngineEvent]:
    rows = conn.execute(
        text(
            "SELECT envelope FROM events WHERE run_id = :r "
            "AND (CAST(:t AS timestamptz) IS NULL OR available_at_utc <= :t) "
            "ORDER BY ord"
        ),
        {"r": run_id, "t": available_by},
    )
    return [EngineEvent.model_validate(r[0]) for r in rows]


def load_overlays(
    conn: Connection, run_id: str, available_by: datetime | None = None
) -> list[OverlayElement]:
    rows = conn.execute(
        text(
            "SELECT element FROM overlay_elements WHERE run_id = :r "
            "AND (CAST(:t AS timestamptz) IS NULL OR avail_at_utc <= :t) ORDER BY ord"
        ),
        {"r": run_id, "t": available_by},
    )
    return [OverlayElement.model_validate(r[0]) for r in rows]
