"""Chart routes (spec/05): instruments, bars, prefs, drawings. Typed for the OpenAPI client."""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nifty.api.auth import check_origin, require_user
from nifty.db import chart
from nifty.db.instruments import find_by_symbol
from nifty.db.session import get_engine
from nifty.timeutil import Calendar

router = APIRouter(dependencies=[Depends(require_user)])
Tf = Literal["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"]


class InstrumentOut(BaseModel):
    instrument_id: str
    tradingsymbol: str
    instrument_type: str | None = None
    tick_size: float | None = None
    lot_size: int | None = None


class BarsOut(BaseModel):
    """Columnar bars; `t` = bar start, UTC epoch seconds."""

    t: list[int]
    o: list[float]
    h: list[float]
    l: list[float]  # noqa: E741
    c: list[float]
    v: list[float]
    flags: list[list[str]]
    volume_kind: str
    next_cursor: int | None = Field(None, description="pass as `cursor` to load older bars")


class Point(BaseModel):
    t: int  # UTC epoch seconds
    p: float


class DrawingData(BaseModel):
    points: list[Point] = Field(min_length=1, max_length=2)
    text: str | None = None
    color: str | None = None


class DrawingIn(BaseModel):
    symbol: str
    kind: Literal["trendline", "hline", "rect", "text"]
    data: DrawingData


class DrawingOut(BaseModel):
    id: str
    kind: Literal["trendline", "hline", "rect", "text"]
    data: DrawingData


class PrefIn(BaseModel):
    value: Any


def _instrument_id(symbol: str) -> str:
    with get_engine().connect() as c:
        ins = find_by_symbol(c, symbol)
    if ins is None:
        raise HTTPException(404, f"unknown symbol {symbol!r}")
    return ins.instrument_id


@router.get("/instruments", response_model=list[InstrumentOut])
def instruments() -> list[dict[str, Any]]:
    with get_engine().connect() as c:
        return chart.list_instruments(c)


@router.get("/bars", response_model=BarsOut)
def bars(
    symbol: str,
    tf: Tf = "1m",
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(5000, ge=1, le=chart.MAX_LIMIT),
    cursor: int | None = Query(None, description="exclusive upper bound, epoch seconds"),
) -> BarsOut:
    iid = _instrument_id(symbol)
    cur = datetime.fromtimestamp(cursor, tz=UTC) if cursor is not None else None
    with get_engine().connect() as c:
        page = chart.bars_page(c, iid, tf, from_, to, limit, cur, Calendar.load())
    return BarsOut(**page.__dict__)


@router.get("/prefs")
def get_prefs() -> dict[str, Any]:
    with get_engine().connect() as c:
        return chart.get_prefs(c)


@router.put("/prefs/{key}", dependencies=[Depends(check_origin)])
def put_pref(key: str, body: PrefIn) -> dict[str, bool]:
    with get_engine().begin() as c:
        chart.set_pref(c, key, body.value)
    return {"ok": True}


@router.get("/drawings", response_model=list[DrawingOut])
def drawings(symbol: str) -> list[dict[str, Any]]:
    iid = _instrument_id(symbol)
    with get_engine().connect() as c:
        return chart.list_drawings(c, iid)


@router.post("/drawings", response_model=DrawingOut, dependencies=[Depends(check_origin)])
def create_drawing(body: DrawingIn) -> dict[str, Any]:
    iid = _instrument_id(body.symbol)
    data = body.data.model_dump(exclude_none=True)
    with get_engine().begin() as c:
        did = chart.create_drawing(c, iid, body.kind, data)
    return {"id": did, "kind": body.kind, "data": data}


@router.put("/drawings/{did}", dependencies=[Depends(check_origin)])
def update_drawing(did: str, body: DrawingData) -> dict[str, bool]:
    with get_engine().begin() as c:
        if not chart.update_drawing(c, did, body.model_dump(exclude_none=True)):
            raise HTTPException(404, "drawing not found")
    return {"ok": True}


@router.delete("/drawings/{did}", dependencies=[Depends(check_origin)])
def delete_drawing(did: str) -> dict[str, bool]:
    with get_engine().begin() as c:
        if not chart.delete_drawing(c, did):
            raise HTTPException(404, "drawing not found")
    return {"ok": True}
