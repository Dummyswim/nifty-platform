"""Research runs: engine x (variant, experiment) over one snapshot -> statistics + verdict + labels.

Checkpoint = one (variant, experiment) cell (the engine is a single stateful pass over the whole
snapshot, so a per-session checkpoint would break state continuity; logged as a deviation).
`progress` holds the finished cells; a rerun after a crash skips them (their labels are idempotent)."""

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from nifty.analytics import research as rs
from nifty.db.backtests import BacktestError, _apply_mode, resolve_input
from nifty.db.runs import persist_run
from nifty.engines.base import get_engine, load_builtin_engines
from nifty.engines.runner import run_batch
from nifty.timeutil import Calendar

ENGINE_ID = "research.distance_entry_v1"
BASELINES = (
    "anchor_cross_ema_order",
    "ema_gap_reexpansion",
    "ema_aligned_gap_reexpansion",
    "armed_resumption",
)
DEFAULT_EXPERIMENTS = (10.0, 20.0)


def label_text(side: str) -> str:
    return "BEARISH INDEX / PUT CANDIDATE" if side == "short" else "BULLISH INDEX / CALL CANDIDATE"


def _clean(o: Any) -> Any:
    """JSON-safe: NaN/inf -> None."""
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


def run_research(conn: Connection, p: dict[str, Any]) -> str:
    """Returns research_id. Same snapshot/variants/experiments/cost/seed/thresholds/code => same id."""
    load_builtin_engines()
    variants = list(p.get("variants") or BASELINES)
    experiments = [float(x) for x in (p.get("experiments") or DEFAULT_EXPERIMENTS)]
    bad = [v for v in variants if v not in BASELINES]
    if bad or not variants or not experiments:
        raise BacktestError(f"variants must be among {list(BASELINES)} and experiments non-empty")
    cost, seed = float(p.get("cost_pts", 0.0)), int(p.get("seed", 1))
    if cost < 0:
        raise BacktestError("cost_pts must be >= 0")
    cal = Calendar.load()
    ins, bars, snapshot_id = resolve_input(conn, p, cal)
    spec = get_engine(ENGINE_ID)
    code = f"{ENGINE_ID}@{spec.cls.version}"
    cfg = {"snap": snapshot_id, "v": variants, "x": experiments, "cost": cost, "seed": seed,
           "th": rs.THRESHOLDS, "code": code}  # fmt: skip
    chash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
    rid = "rr_" + chash[:16]
    sessions = sorted({cal.session_date(b.bar_start_utc) for b in bars})
    assign = rs.split_sessions(sessions)
    splits = {sp: [s.isoformat() for s in sessions if assign[s] == sp] for sp in rs.SPLITS}
    eng = conn.engine  # own transactions: checkpoints and failures must outlive a rolled-back job
    with eng.begin() as w:
        w.execute(
        text(
            "INSERT INTO research_runs (research_id, snapshot_id, instrument_id, config_hash, seed, "
            "cost_pts, splits, variants, code_version, thresholds) VALUES (:r, :s, :i, :h, :sd, :c, "
            "CAST(:sp AS jsonb), CAST(:v AS jsonb), :code, CAST(:th AS jsonb)) ON CONFLICT DO NOTHING"
        ),
        {"r": rid, "s": snapshot_id, "i": ins.instrument_id, "h": chash, "sd": seed, "c": cost,
         "sp": json.dumps(splits), "v": json.dumps({"variants": variants, "experiments": experiments}),
         "code": code, "th": json.dumps(rs.THRESHOLDS)},
        )  # fmt: skip
        row = w.execute(
            text("SELECT status, progress FROM research_runs WHERE research_id = :r"), {"r": rid}
        ).one()
    if row[0] == "done":
        return rid
    progress: dict[str, Any] = dict(row[1] or {})
    first = {sp: cal.session_bounds(date.fromisoformat(v[0]))[0] for sp, v in splits.items() if v}
    try:
        cells: list[dict[str, Any]] = []
        for v in variants:
            for x in experiments:
                key = f"{v}|{x:g}"
                params = {"baseline": v, "target_pts": x, "cost_pts": cost}
                r = run_batch(ENGINE_ID, params, bars, "1m", instrument=ins, calendar=cal,
                              source_id=snapshot_id)  # fmt: skip
                max_hold = timedelta(minutes=int(r.params["max_hold_bars"]))
                trades = _apply_mode(r, "conservative", 1.0, cost)
                if key not in progress:
                    with eng.begin() as w:
                        run_id, _ = persist_run(w, r)
                    ev = rs.evaluate(trades, sessions, cal.session_date, first, max_hold, seed)
                    ev = _clean(ev)
                    vd = rs.verdict(ev, len(sessions))
                    progress[key] = {"variant": v, "experiment": x, "run_id": run_id,
                                     "stats": ev, "verdict": vd, "config_hash": r.config_hash}  # fmt: skip
                    with eng.begin() as w:
                        _labels(w, rid, r.config_hash, ins.instrument_id, v, f"target_{x:g}", run_id,
                            trades, assign, cal.session_date)  # fmt: skip
                        w.execute(
                            text(
                                "UPDATE research_runs SET progress = CAST(:p AS jsonb) WHERE research_id = :r"
                            ),
                            {"p": json.dumps(progress), "r": rid},
                        )  # checkpoint: a crash resumes after this cell
                cells.append(progress[key])
    except Exception as e:
        with eng.begin() as w:
            w.execute(
                text("UPDATE research_runs SET status='failed', error=:e WHERE research_id=:r"),
                {"e": f"{type(e).__name__}: {e}"[:300], "r": rid},
            )
        raise
    top = rs.run_verdict(cells, len(sessions))
    result = {
        "cells": cells,
        "verdict": top,
        "n_sessions": len(sessions),
        "thresholds": rs.THRESHOLDS,
    }
    with eng.begin() as w:
        w.execute(
        text("UPDATE research_runs SET status='done', result = CAST(:res AS jsonb), error = NULL "
             "WHERE research_id = :r"),
        {"res": json.dumps(_clean(result)), "r": rid},
    )  # fmt: skip
    return rid


def _labels(conn, rid, chash, iid, variant, experiment, run_id, trades, assign, session_of) -> None:  # type: ignore[no-untyped-def]
    rows = [
        {"r": rid, "e": ENGINE_ID, "h": chash, "i": iid, "sb": t.signal_bar_start, "sd": t.side,
         "v": variant, "x": experiment, "sp": assign[session_of(t.entry_time)], "run": run_id,
         "l": label_text(t.side), "t": t.model_dump_json()}
        for t in trades if t.signal_bar_start is not None
    ]  # fmt: skip
    if rows:
        conn.execute(
            text(
                "INSERT INTO research_labels (research_id, engine_id, config_hash, instrument_id, "
                "signal_bar_start, side, variant, experiment, split, run_id, label, trade) VALUES "
                "(:r, :e, :h, :i, :sb, :sd, :v, :x, :sp, :run, :l, CAST(:t AS jsonb)) "
                "ON CONFLICT DO NOTHING"
            ),
            rows,
        )


def list_runs(conn: Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT research_id, snapshot_id, instrument_id, status, seed, cost_pts, created_at, "
            "result->'verdict'->>'verdict' AS verdict, error FROM research_runs "
            "ORDER BY created_at DESC LIMIT :n"
        ),
        {"n": limit},
    ).mappings()
    return [dict(r) for r in rows]


def get_run(conn: Connection, rid: str) -> dict[str, Any] | None:
    row = (
        conn.execute(text("SELECT * FROM research_runs WHERE research_id = :r"), {"r": rid})
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def labels_page(conn: Connection, rid: str, variant: str | None, experiment: str | None,
                offset: int, limit: int) -> list[dict[str, Any]]:  # fmt: skip
    rows = conn.execute(
        text(
            "SELECT id, variant, experiment, split, side, signal_bar_start, run_id, label, trade "
            "FROM research_labels WHERE research_id = :r AND (CAST(:v AS text) IS NULL OR variant = :v) "
            "AND (CAST(:x AS text) IS NULL OR experiment = :x) ORDER BY signal_bar_start, id "
            "OFFSET :o LIMIT :l"
        ),
        {"r": rid, "v": variant, "x": experiment, "o": offset, "l": limit},
    ).mappings()
    return [dict(r) for r in rows]
