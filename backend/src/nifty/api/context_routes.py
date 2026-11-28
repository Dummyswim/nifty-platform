"""Market context: per-minute VIX rank, CE/PE premium verdicts, option writing and bias."""

import json
import threading
from datetime import UTC, date, datetime
from datetime import date as Day  # `date` is also a ContextOut field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError

from nifty.api.auth import require_user
from nifty.context.params import ContextParams, Writing
from nifty.context.series import build_series
from nifty.db import chart
from nifty.db.context import last_closed_minute, load_day, session_for
from nifty.db.session import get_engine
from nifty.timeutil import Calendar

router = APIRouter(dependencies=[Depends(require_user)])

_CACHE_MAX = 16
_CACHE: dict[tuple[str, date, str, int | None, str], "ContextOut"] = {}
_CACHE_LOCK = threading.Lock()  # sync routes run in the threadpool
_OPTION_PREFS = ("options.r", "options.max_stale_s", "options.window_steps")


class SideOut(BaseModel):
    iv: float | None = None
    verdict: str | None = None
    own_iv: float | None = None
    note: str | None = None


class WallOut(BaseModel):
    strike: float
    oi: float
    edge: bool


class StateOut(BaseModel):
    t: int
    vix: float | None = None
    vix_rank: float | None = None
    vix_high: bool | None = None
    ce: SideOut
    pe: SideOut
    rv: float | None = None
    straddle_prem: float | None = None
    fair_straddle_prem: float | None = None
    w_day: float | None = None
    w_roll: float | None = None
    oi_ce: float | None = None
    oi_pe: float | None = None
    one_sided: int | None = None
    candidate: str
    bias: str
    bias_since: int | None = None
    exp_move_pts: float | None = None
    day_move_pts: float | None = None
    room_left_pts: float | None = None
    used_pct: float | None = None
    late: bool | None = None
    call_wall: WallOut | None = None
    put_wall: WallOut | None = None
    na_reason: str | None = None
    flags: list[str]
    writing: str


class ContextOut(BaseModel):
    underlying: str
    writing: str
    date: Day | None = None
    expiry: Day | None = None
    params: dict[str, Any]
    series: list[StateOut]
    notes: list[str]


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


@router.get("/context", response_model=ContextOut)
def context(
    underlying: str = "NIFTY", day: date | None = Query(None, alias="date"),
    writing: Writing = "iv",
) -> ContextOut:  # fmt: skip
    if underlying != "NIFTY":
        raise HTTPException(404, f"no context for {underlying}")
    now = datetime.now(UTC)
    with get_engine().connect() as c:
        prefs = chart.get_prefs(c)
        try:
            shared, own = prefs.get("context") or {}, prefs.get(f"context.{writing}") or {}
            p = ContextParams(**{**shared, **own, "writing": writing})
        except (TypeError, ValidationError) as e:
            raise HTTPException(422, f"invalid context prefs: {e}") from e
        params = p.model_dump()
        sess = session_for(c, Calendar.load(), day, now)
        if sess is None:
            shown = day or Calendar.session_date(now)
            return ContextOut(underlying=underlying, writing=writing, date=day, params=params,
                              series=[], notes=[f"no session data for {shown}"])  # fmt: skip
        last = last_closed_minute(c, sess, now)
        cfg = {"params": params, **{k: prefs.get(k) for k in _OPTION_PREFS}}
        key = (underlying, sess, writing, None if last is None else int(last.timestamp()),
               json.dumps(cfg, sort_keys=True))  # fmt: skip
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
        if hit is not None:
            return hit
        inp = load_day(c, underlying, sess, now, prefs)
    expiry, series, notes = build_series(inp, p)
    out = ContextOut(underlying=underlying, writing=writing, date=sess, expiry=expiry,
                     params=params, series=[StateOut.model_validate(s) for s in series],
                     notes=notes)  # fmt: skip
    with _CACHE_LOCK:
        while len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)), None)  # oldest insertion
        _CACHE[key] = out
    return out
