"""Live persistence: ticks, collector status, incremental engine outputs (source_id live:<iid>)."""

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from nifty.collector.packets import PacketTick
from nifty.engines.live import LiveDelta, LiveRun


def live_run_id(run: LiveRun) -> str:
    raw = "|".join([run.engine_id, run.version, run.config_hash, run.source_id, run.timeframe])
    return "run_" + hashlib.sha256(raw.encode()).hexdigest()[:16]  # same key rule as persist_run


def ensure_live_run(conn: Connection, run: LiveRun, instrument_id: str) -> str:
    rid = live_run_id(run)
    raw = "|".join([run.engine_id, run.version, run.config_hash, run.source_id, run.timeframe])
    conn.execute(
        text(
            "INSERT INTO engine_configs (config_hash, engine_id, engine_version, params) "
            "VALUES (:c, :e, :v, CAST(:p AS jsonb)) ON CONFLICT DO NOTHING"
        ),
        {"c": run.config_hash, "e": run.engine_id, "v": run.version, "p": json.dumps(run.params)},
    )
    conn.execute(
        text(
            "INSERT INTO engine_runs (run_id, run_key, engine_id, engine_version, config_hash, "
            "instrument_id, timeframe, source_id, n_bars) VALUES (:id, :k, :e, :v, :c, :i, :tf, :s, 0) "
            "ON CONFLICT (run_key) DO NOTHING"
        ),
        {
            "id": rid, "k": hashlib.sha256(raw.encode()).hexdigest(), "e": run.engine_id,
            "v": run.version, "c": run.config_hash, "i": instrument_id, "tf": run.timeframe,
            "s": run.source_id,
        },
    )  # fmt: skip
    return rid


def clear_live_outputs(conn: Connection, run_id: str) -> None:
    """A restart replays a sliding warm-up window, so overlay ids (zone seq) and ords restart and
    would collide with the previous window's rows; the replay must replace them, not merge."""
    for table in ("plot_points", "events", "overlay_elements"):
        conn.execute(text(f"DELETE FROM {table} WHERE run_id = :r"), {"r": run_id})  # noqa: S608


def append_delta(conn: Connection, run_id: str, d: LiveDelta) -> None:
    """Idempotent: every row has a key (bar start / event id / overlay id+ver)."""
    if d.plots:
        conn.execute(
            text(
                "INSERT INTO plot_points (run_id, bar_start_utc, values) VALUES (:r, :t, CAST(:v AS jsonb)) "
                "ON CONFLICT DO NOTHING"
            ),
            [{"r": run_id, "t": t, "v": json.dumps(v, allow_nan=False)} for t, v in d.plots],
        )
    if d.events:
        conn.execute(
            text(
                "INSERT INTO events (run_id, ord, event_id, event_type, bar_start_utc, available_at_utc, "
                "confirmed_or_provisional, envelope) VALUES (:r, :o, :id, :ty, :bs, :av, :cp, "
                "CAST(:env AS jsonb)) ON CONFLICT DO NOTHING"
            ),
            [
                {
                    "r": run_id, "o": o, "id": str(e.event_id), "ty": e.event_type,
                    "bs": e.bar_start_utc, "av": e.available_at_utc,
                    "cp": e.confirmed_or_provisional, "env": e.model_dump_json(),
                }
                for o, e in d.events
            ],
        )  # fmt: skip
    if d.overlays:
        conn.execute(
            text(
                "INSERT INTO overlay_elements (run_id, ord, id, ver, avail_at_utc, deleted, element) "
                "VALUES (:r, :o, :id, :ver, :av, :d, CAST(:el AS jsonb)) ON CONFLICT DO NOTHING"
            ),
            [
                {
                    "r": run_id, "o": o, "id": e.id, "ver": e.ver, "av": e.avail_at_utc,
                    "d": e.deleted, "el": e.model_dump_json(),
                }
                for o, e in d.overlays
            ],
        )  # fmt: skip
    if d.panel is not None:
        conn.execute(
            text(
                "UPDATE engine_runs SET panel = CAST(:p AS jsonb), "
                "n_bars = (SELECT count(*) FROM plot_points WHERE run_id = :r) WHERE run_id = :r"
            ),
            {"p": json.dumps(d.panel, default=str, allow_nan=False), "r": run_id},
        )


def insert_ticks(conn: Connection, rows: list[tuple[str, PacketTick, datetime]]) -> None:
    if not rows:
        return
    conn.execute(
        text(
            "INSERT INTO ticks (instrument_id, ts_exchange, ts_received, ltp, volume_traded, oi, bid, "
            "ask, bid_qty, ask_qty) VALUES (:i, :te, :tr, :ltp, :v, :oi, :b, :a, :bq, :aq)"
        ),
        [
            {
                "i": iid, "te": t.exchange_ts or t.last_ts or recv, "tr": recv, "ltp": t.ltp,
                "v": t.volume, "oi": t.oi, "b": t.bid, "a": t.ask, "bq": t.bid_qty, "aq": t.ask_qty,
            }
            for iid, t, recv in rows
        ],
    )  # fmt: skip


def write_status(conn: Connection, data: dict[str, Any]) -> None:
    conn.execute(
        text(
            "INSERT INTO collector_status (id, data, updated_at) VALUES (1, CAST(:d AS jsonb), now()) "
            "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()"
        ),
        {"d": json.dumps(data, default=str)},
    )


def read_status(conn: Connection) -> tuple[dict[str, Any], float] | None:
    """(data, age in seconds) or None when no collector ever ran."""
    row = conn.execute(
        text(
            "SELECT data, extract(epoch FROM now() - updated_at) FROM collector_status WHERE id = 1"
        )
    ).first()
    return None if row is None else (dict(row[0]), float(row[1]))


STATUS_FRESH_S = 10.0


def status_summary(row: tuple[dict[str, Any], float] | None) -> dict[str, Any]:
    """Collector status for the API/UI: state is live | stale | disconnected | auth_expired | down."""
    if row is None:
        return {"state": "down", "connected": False, "stale": False, "auth_expired": False,
                "detail": "no collector has run", "instruments": [], "ticks": 0, "reconnects": 0,
                "redis": False, "provider": None, "last_tick_age_s": None, "updated_age_s": None}  # fmt: skip
    d, age = row
    if age > STATUS_FRESH_S:
        state = "down"
    elif d.get("auth_expired"):
        state = "auth_expired"
    elif not d.get("connected"):
        state = "disconnected"
    elif d.get("stale"):
        state = "stale"
    else:
        state = "live"
    return {
        "state": state, "connected": bool(d.get("connected")), "stale": bool(d.get("stale")),
        "auth_expired": bool(d.get("auth_expired")), "detail": d.get("detail", ""),
        "instruments": d.get("instruments", []), "ticks": int(d.get("ticks", 0)),
        "reconnects": int(d.get("reconnects", 0)), "redis": bool(d.get("redis")),
        "provider": d.get("provider"), "last_tick_age_s": d.get("last_tick_age_s"),
        "updated_age_s": round(age, 1),
    }  # fmt: skip
