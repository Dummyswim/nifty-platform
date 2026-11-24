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
from nifty.contracts import EngineEvent, OverlayElement, PlotSpec, TradeRecord
from nifty.db import backtests as bt
from nifty.db.instruments import upsert_instrument
from nifty.db.jobs import get_job, submit_job
from nifty.db.runs import load_events, load_overlays, load_plots
from nifty.db.session import get_engine
from nifty.engines.base import EngineNotFound, EngineNotReady, list_engines
from nifty.engines.base import get_engine as get_engine_spec

router = APIRouter(dependencies=[Depends(require_user)])


class EngineOut(BaseModel):
    id: str
    version: str
    default_timeframe: str
    ready: bool
    params_schema: dict[str, Any] = Field(
        description="JSON Schema of Params; `ui` fields tagged x-ui"
    )
    plots: list[PlotSpec] = Field(default_factory=list)


class SubmitOut(BaseModel):
    job_id: int
    created: bool
    status: str | None = None
    result_ref: str | None = None


class JobOut(BaseModel):
    id: int
    kind: str
    status: str
    attempts: int
    error: str | None = None
    result_ref: str | None = None
    backtest_id: str | None = None


class OptionPolicyIn(BaseModel):
    strike_type: Literal["Deep ITM", "ITM", "ATM", "OTM", "Deep OTM"] = "ATM"
    expiry_kind: Literal["current weekly", "next weekly", "monthly"] = "current weekly"
    lots: int = Field(1, ge=1)
    cost_inr: float = Field(0.0, ge=0)
    max_stale_s: float = Field(60.0, gt=0)


class OptionSummary(BaseModel):
    """CE/PE paper mapping totals (INR, never mixed with index points)."""

    n_mapped: int
    no_quote: int
    no_contract: int
    total_pnl_inr: float
    cost_inr: float
    policy: dict[str, Any]


class MetricsOut(BaseModel):
    n_trades: int
    wins: int
    losses: int
    win_rate: float | None
    gross_profit_pts: float
    gross_loss_pts: float
    profit_factor: float | None
    total_pnl_pts: float
    expectancy_pts: float | None
    max_drawdown_pts: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    sharpe: float | None
    n_sessions: int
    low_n: bool
    flags: list[str]
    option: OptionSummary | None = None


class BacktestOut(BaseModel):
    backtest_id: str
    run_id: str
    engine_id: str
    instrument_id: str
    snapshot_id: str
    timeframe: str
    mode: str
    qty: float
    cost_pts: float
    params: dict[str, Any]
    summary: MetricsOut
    created_at: datetime


class BacktestRow(BaseModel):
    backtest_id: str
    engine_id: str
    instrument_id: str
    snapshot_id: str
    timeframe: str
    mode: str
    created_at: datetime
    n_trades: int | None = None
    total_pnl_pts: float | None = None


class WindowBar(BaseModel):
    t: datetime
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float


class AuditOut(BaseModel):
    trade: TradeRecord
    levels: dict[str, float | None]
    strike: float | None = None
    option_type: str | None = None
    pnl_pts: float
    pnl_inr: float | None = None
    roi_pct: float | None = None
    stop_hit: bool
    target_hit: bool
    exit_reason: str
    window_bars: list[WindowBar]
    events: list[EngineEvent]


class PlotsOut(BaseModel):
    run_id: str
    timeframe: str
    t: list[int] = Field(description="engine bar start, UTC epoch seconds")
    series: dict[str, list[float | None]]
    panel: dict[str, Any] | None = None


class EventsOut(BaseModel):
    run_id: str
    events: list[EngineEvent]


class OverlaysOut(BaseModel):
    run_id: str
    overlays: list[OverlayElement]


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
    option_policy: OptionPolicyIn | None = None


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


@router.get("/engines", response_model=list[EngineOut])
def engines() -> list[dict[str, Any]]:
    return [
        {
            **{k: e[k] for k in ("id", "version", "default_timeframe", "ready")},
            "params_schema": e["schema"],
            "plots": e["plots"],
        }
        for e in list_engines()
    ]


@router.post(
    "/engines/{engine_id}/run",
    status_code=202,
    response_model=SubmitOut,
    dependencies=[Depends(check_origin)],
)
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


@router.get("/jobs/{job_id}", response_model=JobOut)
def job(job_id: int) -> dict[str, Any]:
    with get_engine().connect() as c:
        j = get_job(c, job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    j["backtest_id"] = (
        j["result_ref"] if j["kind"] == "backtest" and j["status"] == "done" else None
    )
    return j


@router.post(
    "/backtests", status_code=202, response_model=SubmitOut, dependencies=[Depends(check_origin)]
)
def create_backtest(body: BacktestIn) -> dict[str, Any]:
    _need_input(body)
    try:
        get_engine_spec(body.engine_id)
    except (EngineNotFound, EngineNotReady) as e:
        raise HTTPException(404, f"engine {body.engine_id} not available") from e
    with _begin() as c:
        jid, created = submit_job(c, "backtest", body.model_dump(exclude_none=True))
        return _job_out(c, jid, created)


@router.get("/backtests", response_model=list[BacktestRow])
def backtests(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    with get_engine().connect() as c:
        return bt.list_backtests(c, limit)


def _backtest(c: Connection, bt_id: str) -> dict[str, Any]:
    row = bt.get_backtest(c, bt_id)
    if row is None:
        raise HTTPException(404, "backtest not found")
    return row


@router.get("/backtests/{bt_id}", response_model=BacktestOut)
def backtest(bt_id: str) -> dict[str, Any]:
    with get_engine().connect() as c:
        return _backtest(c, bt_id)


@router.get("/backtests/{bt_id}/trades", response_model=list[TradeRecord])
def backtest_trades(bt_id: str) -> list[dict[str, Any]]:
    with get_engine().connect() as c:
        _backtest(c, bt_id)
        return [t.model_dump(mode="json") for t in bt.load_trades(c, bt_id)]


@router.get("/backtests/{bt_id}/analytics", response_model=MetricsOut)
def backtest_analytics(bt_id: str) -> dict[str, Any]:
    with get_engine().connect() as c:
        return dict(_backtest(c, bt_id)["summary"])


@router.get("/backtests/{bt_id}/audit/{trade_id}", response_model=AuditOut)
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


@router.get("/plots", response_model=PlotsOut)
def plots(
    run_id: str | None = None, engine_id: str | None = None, snapshot_id: str | None = None,
    timeframe: str | None = None, config_hash: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    with get_engine().connect() as c:
        rid = _find_run(c, run_id, engine_id, snapshot_id, timeframe, config_hash)
        rows = load_plots(c, rid)
        meta = c.execute(
            text("SELECT timeframe, panel FROM engine_runs WHERE run_id = :r"), {"r": rid}
        ).one()
    names = sorted({k for _, v in rows for k in v})
    return {
        "run_id": rid,
        "timeframe": meta[0],
        "panel": meta[1],
        "t": [int(t.timestamp()) for t, _ in rows],
        "series": {n: [v.get(n) for _, v in rows] for n in names},
    }


@router.get("/events", response_model=EventsOut)
def events(
    run_id: str | None = None, engine_id: str | None = None, snapshot_id: str | None = None,
    timeframe: str | None = None, config_hash: str | None = None,
    available_by: datetime | None = None,
) -> dict[str, Any]:  # fmt: skip
    with get_engine().connect() as c:
        rid = _find_run(c, run_id, engine_id, snapshot_id, timeframe, config_hash)
        ev = load_events(c, rid, available_by)
    return {"run_id": rid, "events": [e.model_dump(mode="json") for e in ev]}


@router.get("/overlays", response_model=OverlaysOut)
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
