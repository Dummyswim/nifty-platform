"""Research routes (C14): create a run (job), list, get with variant tables + verdict, labels."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nifty.api.auth import check_origin, require_user
from nifty.api.routes import SubmitOut, _job_out
from nifty.contracts import TradeRecord
from nifty.db import research as dbr
from nifty.db.jobs import submit_job
from nifty.db.session import get_engine

router = APIRouter(prefix="/research", dependencies=[Depends(require_user)])


class ResearchIn(BaseModel):
    snapshot_id: str | None = None
    symbol: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    variants: list[str] | None = None
    experiments: list[float] | None = Field(
        default=None, description="target_pts, one experiment each"
    )
    cost_pts: float = Field(0.0, ge=0)
    seed: int = 1


class ResearchRow(BaseModel):
    research_id: str
    snapshot_id: str
    instrument_id: str
    status: str
    seed: int
    cost_pts: float
    created_at: datetime
    verdict: str | None = None
    error: str | None = None


class ResearchOut(ResearchRow):
    config_hash: str
    code_version: str
    splits: dict[str, list[str]]
    variants: dict[str, Any]
    thresholds: dict[str, Any]
    progress_cells: int
    result: dict[str, Any] | None = Field(
        default=None, description="cells (variant x experiment tables), verdict, thresholds"
    )


class LabelOut(BaseModel):
    id: int
    variant: str
    experiment: str
    split: str
    side: str
    signal_bar_start: datetime
    run_id: str
    label: str
    trade: TradeRecord


@router.post(
    "/runs", status_code=202, response_model=SubmitOut, dependencies=[Depends(check_origin)]
)
def create_run(body: ResearchIn) -> dict[str, Any]:
    if not (body.snapshot_id or body.symbol):
        raise HTTPException(422, "snapshot_id or symbol required")
    bad = [v for v in body.variants or [] if v not in dbr.BASELINES]
    if bad:
        raise HTTPException(422, f"unknown variants {bad}")
    with get_engine().begin() as c:
        jid, created = submit_job(c, "research_run", body.model_dump(exclude_none=True))
        return _job_out(c, jid, created)


@router.get("/runs", response_model=list[ResearchRow])
def runs(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    with get_engine().connect() as c:
        return dbr.list_runs(c, limit)


@router.get("/runs/{rid}", response_model=ResearchOut)
def run(rid: str) -> dict[str, Any]:
    with get_engine().connect() as c:
        row = dbr.get_run(c, rid)
    if row is None:
        raise HTTPException(404, "research run not found")
    row["progress_cells"] = len(row.pop("progress") or {})
    row["verdict"] = ((row["result"] or {}).get("verdict") or {}).get("verdict")
    return row


@router.get("/runs/{rid}/labels", response_model=list[LabelOut])
def labels(
    rid: str, variant: str | None = None, experiment: str | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:  # fmt: skip
    with get_engine().connect() as c:
        if dbr.get_run(c, rid) is None:
            raise HTTPException(404, "research run not found")
        return dbr.labels_page(c, rid, variant, experiment, offset, limit)
