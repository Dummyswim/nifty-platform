"""Data/engine/backtest routes (spec/05). All need the session cookie; POSTs check Origin."""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from nifty.analytics.export import to_csv, to_json, to_xlsx
from nifty.api.auth import check_origin, require_user
from nifty.db import backtests as bt
from nifty.db.instruments import upsert_instrument
from nifty.db.jobs import get_job, submit_job
from nifty.db.runs import load_events, load_overlays, load_plots
from nifty.db.session import get_engine
from nifty.engines.base import EngineNotFound, EngineNotReady, list_engines
from nifty.engines.base import get_engine as get_engine_spec

router = APIRouter(dependencies=[Depends(require_user)])
MAX_UPLOAD = 25 * 1024 * 1024


class RunIn(BaseModel):
    symbol: str | None = None
    snapshot_id: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    timeframe: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class BacktestIn(RunIn):
    engine_id: str
    mode: Literal["tv", "conservative"] = "tv"
    qty: float = Field(1.0, gt=0)
    cost_pts: float = Field(0.0, ge=0)


def _begin() -> Any:
    return get_engine().begin()


def _need_input(b: RunIn) -> None:
    if not (b.snapshot_id or b.symbol):
        raise HTTPException(422, "snapshot_id or symbol required")


def _job_out(conn: Connection, job_id: int, created: bool) -> dict[str, Any]:
    j = get_job(conn, job_id) or {}
    return {
        "job_id": job_id,
        "created": created,
        "status": j.get("status"),
        "result_ref": j.get("result_ref"),
    }


@router.get("/engines")
def engines() -> list[dict[str, Any]]:
    return list_engines()


@router.post("/engines/{engine_id}/run", status_code=202, dependencies=[Depends(check_origin)])
def engine_run(engine_id: str, body: RunIn) -> dict[str, Any]:
    _need_input(body)
    try:
        get_engine_spec(engine_id)
    except (EngineNotFound, EngineNotReady) as e:
        raise HTTPException(404, f"engine {engine_id} not available") from e
    payload = {"engine_id": engine_id, **body.model_dump(exclude_none=True)}
    with _begin() as c:
        jid, created = submit_job(c, "engine_run", payload)
        return _job_out(c, jid, created)


@router.get("/jobs/{job_id}")
def job(job_id: int) -> dict[str, Any]:
    with get_engine().connect() as c:
        j = get_job(c, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    j["backtest_id"] = (
        j["result_ref"] if j["kind"] == "backtest" and j["status"] == "done" else None
    )
    return j


@router.post("/backtests", status_code=202, dependencies=[Depends(check_origin)])
def create_backtest(body: BacktestIn) -> dict[str, Any]:
    _need_input(body)
    try:
        get_engine_spec(body.engine_id)
    except (EngineNotFound, EngineNotReady) as e:
        raise HTTPException(404, f"engine {body.engine_id} not available") from e
    with _begin() as c:
        jid, created = submit_job(c, "backtest", body.model_dump(exclude_none=True))
        return _job_out(c, jid, created)


@router.get("/backtests")
def backtests(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    with get_engine().connect() as c:
        return bt.list_backtests(c, limit)


def _backtest(c: Connection, bt_id: str) -> dict[str, Any]:
    row = bt.get_backtest(c, bt_id)
    if row is None:
        raise HTTPException(404, "backtest not found")
    return row


@router.get("/backtests/{bt_id}")
def backtest(bt_id: str) -> dict[str, Any]:
    with get_engine().connect() as c:
        return _backtest(c, bt_id)


@router.get("/backtests/{bt_id}/trades")
def backtest_trades(bt_id: str) -> list[dict[str, Any]]:
    with get_engine().connect() as c:
        _backtest(c, bt_id)
        return [t.model_dump(mode="json") for t in bt.load_trades(c, bt_id)]


@router.get("/backtests/{bt_id}/analytics")
def backtest_analytics(bt_id: str) -> dict[str, Any]:
    with get_engine().connect() as c:
        return dict(_backtest(c, bt_id)["summary"])


@router.get("/backtests/{bt_id}/audit/{trade_id}")
def backtest_audit(
    bt_id: str, trade_id: str, window: int = Query(10, ge=0, le=100)
) -> dict[str, Any]:
    with get_engine().connect() as c:
        out = bt.audit_trade(c, bt_id, trade_id, window)
    if out is None:
        raise HTTPException(404, "trade not found")
    return out


@router.get("/backtests/{bt_id}/export")
def backtest_export(bt_id: str, fmt: Literal["csv", "xlsx", "json"] = "csv") -> Response:
    with get_engine().connect() as c:
        summary = _backtest(c, bt_id)["summary"]
        trades = bt.load_trades(c, bt_id)
    name = f"{bt_id}.{fmt}"
    head = {"Content-Disposition": f'attachment; filename="{name}"'}
    if fmt == "csv":
        return Response(to_csv(trades), media_type="text/csv", headers=head)
    if fmt == "json":
        return Response(to_json(trades, summary), media_type="application/json", headers=head)
    return Response(
        to_xlsx(trades, summary),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=head,
    )


def _find_run(
    c: Connection, run_id: str | None, engine_id: str | None, snapshot_id: str | None,
    timeframe: str | None, config_hash: str | None,
) -> str:  # fmt: skip
    if run_id:
        if c.execute(text("SELECT 1 FROM engine_runs WHERE run_id = :r"), {"r": run_id}).first():
            return run_id
        raise HTTPException(404, "run not found")
    if not (engine_id and snapshot_id):
        raise HTTPException(422, "run_id, or engine_id + snapshot_id (+ timeframe, config_hash)")
    row = c.execute(
        text(
            "SELECT run_id FROM engine_runs WHERE engine_id = :e AND source_id = :s "
            "AND (CAST(:tf AS text) IS NULL OR timeframe = :tf) "
            "AND (CAST(:h AS text) IS NULL OR config_hash = :h) ORDER BY created_at DESC LIMIT 1"
        ),
        {"e": engine_id, "s": snapshot_id, "tf": timeframe, "h": config_hash},
    ).first()
    if row is None:
        raise HTTPException(404, "no matching run")
    return str(row[0])


@router.get("/plots")
def plots(
    run_id: str | None = None, engine_id: str | None = None, snapshot_id: str | None = None,
    timeframe: str | None = None, config_hash: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    with get_engine().connect() as c:
        rid = _find_run(c, run_id, engine_id, snapshot_id, timeframe, config_hash)
        rows = load_plots(c, rid)
    names = sorted({k for _, v in rows for k in v})
    return {
        "run_id": rid,
        "t": [t.isoformat() for t, _ in rows],
        "series": {n: [v.get(n) for _, v in rows] for n in names},
    }


@router.get("/events")
def events(
    run_id: str | None = None, engine_id: str | None = None, snapshot_id: str | None = None,
    timeframe: str | None = None, config_hash: str | None = None,
    available_by: datetime | None = None,
) -> dict[str, Any]:  # fmt: skip
    with get_engine().connect() as c:
        rid = _find_run(c, run_id, engine_id, snapshot_id, timeframe, config_hash)
        ev = load_events(c, rid, available_by)
    return {"run_id": rid, "events": [e.model_dump(mode="json") for e in ev]}


@router.get("/overlays")
def overlays(
    run_id: str | None = None, engine_id: str | None = None, snapshot_id: str | None = None,
    timeframe: str | None = None, config_hash: str | None = None,
    available_by: datetime | None = None,
) -> dict[str, Any]:  # fmt: skip
    with get_engine().connect() as c:
        rid = _find_run(c, run_id, engine_id, snapshot_id, timeframe, config_hash)
        ov = load_overlays(c, rid, available_by)
    return {"run_id": rid, "overlays": [o.model_dump(mode="json") for o in ov]}


@router.post("/datasets/import", dependencies=[Depends(check_origin)])
async def import_dataset(
    request: Request,
    symbol: str = Query(min_length=1),
    tick_size: float = Query(gt=0, description="never inferred"),
    tz: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Upload a 1m CSV (text/csv) or JSON (application/json) as the raw request body."""
    from nifty.contracts import Instrument
    from nifty.db.bars import upsert_bars
    from nifty.marketdata.importer import ImportRejected, parse_file
    from nifty.marketdata.validation import validate_bars
    from nifty.timeutil import Calendar

    body = await request.body()
    if not body or len(body) > MAX_UPLOAD:
        raise HTTPException(413 if body else 422, "empty or too large (25 MB max)")
    suffix = (
        ".json"
        if request.headers.get("content-type", "").startswith("application/json")
        else ".csv"
    )
    iid = f"csv:{symbol}"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"upload{suffix}"
        p.write_bytes(body)
        try:
            raw = parse_file(p, instrument_id=iid, tz=tz)
        except ImportRejected as e:
            raise HTTPException(422, f"rejected: {e}") from e
    bars, r = validate_bars(raw, Calendar.load())
    out: dict[str, Any] = {
        "rows_in": r.rows_in, "accepted": r.rows_ok, "excluded": len(r.excluded),
        "duplicates": r.duplicates, "out_of_order": r.out_of_order,
        "gaps": len(r.gaps), "sessions": len(r.sessions), "volume_kind": r.volume_kind,
        "calendar_unverified": r.calendar_unverified, "stored": False,
    }  # fmt: skip
    if not dry_run:
        with _begin() as c:
            upsert_instrument(
                c,
                Instrument(
                    instrument_id=iid, provider="csv", tradingsymbol=symbol, tick_size=tick_size
                ),
            )
            u = upsert_bars(c, bars)
        out.update(stored=True, inserted=u.inserted, revised=u.revised, unchanged=u.noop)
    return out
