"""Options routes (C12): expiries, chain (recorded quotes + computed Greeks), contract bars."""

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from nifty.api.auth import require_user
from nifty.api.chart_routes import BarsOut, Tf
from nifty.contracts import Instrument
from nifty.db import chart
from nifty.db import options as dbo
from nifty.db.instruments import get_instrument, option_instruments
from nifty.db.session import get_engine
from nifty.options.bs import LABEL, bs, effective_today, implied_vol, years_to_expiry
from nifty.options.chain import (
    DEFAULT_OFFSETS,
    STRIKE_TYPES,
    atm,
    expiry_kinds,
    strike_for,
    strike_step,
)
from nifty.timeutil import Calendar

router = APIRouter(prefix="/options", dependencies=[Depends(require_user)])


class ExpiriesOut(BaseModel):
    underlying: str
    kinds: dict[str, date | None] = Field(
        description="current weekly | next weekly | monthly; null = unavailable"
    )
    expiries: list[date]
    step: float | None = None


class Side(BaseModel):
    contract_id: str
    recorded: bool
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    age_s: float | None = None
    oi: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta_day: float | None = None
    vega_1pct: float | None = None
    greeks: str = "n/a"
    greeks_note: str | None = None


class Row(BaseModel):
    strike: float
    atm: bool
    ce: Side | None = None
    pe: Side | None = None


class ChainOut(BaseModel):
    underlying: str
    expiry: date
    spot: float | None = None
    spot_age_s: float | None = None
    atm: float | None = None
    step: float | None = None
    r_set: bool
    picks: dict[str, dict[str, float | None]] = Field(description="strike type -> {CE, PE} strike")
    rows: list[Row]
    note: str | None = None


class OiOut(BaseModel):
    t: list[int]
    v: list[float]


class ContractBarsOut(BaseModel):
    contract_id: str
    bars: BarsOut | None = None
    oi: OiOut
    coverage: dict[str, Any]


def _prefs(c: Connection) -> dict[str, Any]:
    return chart.get_prefs(c)


@router.get("/expiries", response_model=ExpiriesOut)
def expiries(underlying: str = "NIFTY") -> dict[str, Any]:
    now = datetime.now(UTC)
    with get_engine().connect() as c:
        ins = option_instruments(c, underlying)
    exps = sorted({o.expiry for o in ins if o.expiry})
    live_strikes = [o.strike for o in ins if o.expiry == (exps[0] if exps else None) and o.strike]
    today = effective_today(now)
    return {
        "underlying": underlying, "kinds": expiry_kinds(exps, today),
        "expiries": [e for e in exps if e >= today], "step": strike_step(live_strikes),
    }  # fmt: skip


def _side(c: Instrument | None, tick: dict[str, Any] | None, cov: bool, spot_px: float | None,
          r: float | None, exp: date, now: datetime, is_call: bool) -> Side | None:  # fmt: skip
    if c is None:
        return None
    s = Side(contract_id=c.instrument_id, recorded=cov)
    if tick is None:
        s.greeks_note = "not recorded" if not cov else "no quote"
        return s
    s.last, s.bid, s.ask, s.oi = tick["ltp"], tick["bid"], tick["ask"], tick["oi"]
    s.age_s = round((now - tick["ts_exchange"]).total_seconds(), 1)
    t = years_to_expiry(exp, now)
    if r is None:
        s.greeks_note = "Greeks n/a: set r in Settings"
    elif spot_px is None or not s.last or c.strike is None or t <= 0:
        s.greeks_note = "Greeks n/a: no spot, price or time left"
    else:
        iv = implied_vol(s.last, spot_px, c.strike, t, r, is_call)
        g = bs(spot_px, c.strike, t, r, iv, is_call) if iv else None
        if g is None:
            s.greeks_note = "Greeks n/a: price outside the model band"
        else:
            s.iv, s.delta, s.gamma, s.theta_day, s.vega_1pct = (
                iv,
                g.delta,
                g.gamma,
                g.theta_day,
                g.vega_1pct,
            )
            s.greeks, s.greeks_note = "computed", LABEL
    return s


@router.get("/chain", response_model=ChainOut)
def chain(expiry: date, underlying: str = "NIFTY", width: int = Query(10, ge=1, le=40)) -> ChainOut:
    now = datetime.now(UTC)
    with get_engine().connect() as c:
        ins = [o for o in option_instruments(c, underlying) if o.expiry == expiry]
        if not ins:
            raise HTTPException(404, f"{expiry} is not a listed expiry for {underlying}")
        prefs = _prefs(c)
        sp = dbo.spot(c)
        ticks = dbo.latest_ticks(c, [o.instrument_id for o in ins])
        recorded = {
            o.instrument_id
            for o in ins
            if o.instrument_id in ticks or dbo.coverage(c, o.instrument_id)["recorded"]
        }
    r = prefs.get("options.r")
    r = float(r) if isinstance(r, (int, float)) else None
    offsets = {
        **DEFAULT_OFFSETS,
        **{
            k: int(v)
            for k, v in (prefs.get("options.strike_offsets") or {}).items()
            if k in STRIKE_TYPES
        },
    }
    strikes = sorted({o.strike for o in ins if o.strike is not None})
    step = strike_step(strikes)
    spot_px = sp[0] if sp else None
    a = atm(spot_px, strikes) if spot_px is not None else None
    centre = a if a is not None else (strikes[len(strikes) // 2] if strikes else 0.0)
    shown = sorted(strikes, key=lambda k: abs(k - centre))[: 2 * width + 1]
    by: dict[tuple[float | None, str | None], Instrument] = {
        (o.strike, o.option_type): o for o in ins
    }

    def side(k: float, ot: str) -> Side | None:
        o = by.get((k, ot))
        if o is None:
            return None
        return _side(
            o,
            ticks.get(o.instrument_id),
            o.instrument_id in recorded,
            spot_px,
            r,
            expiry,
            now,
            ot == "CE",
        )

    rows = [Row(strike=k, atm=(k == a), ce=side(k, "CE"), pe=side(k, "PE")) for k in sorted(shown)]
    picks: dict[str, dict[str, float | None]] = {}
    if a is not None and step is not None:
        picks = {
            t: {ot: strike_for(t, ot, a, step, strikes, offsets) for ot in ("CE", "PE")}
            for t in STRIKE_TYPES
        }
    note = None if sp else "no spot: no NIFTY 50 bars stored yet"
    return ChainOut(
        underlying=underlying, expiry=expiry, spot=spot_px,
        spot_age_s=None if sp is None else round((now - sp[1]).total_seconds(), 1),
        atm=a, step=step, r_set=r is not None, picks=picks, rows=rows, note=note,
    )  # fmt: skip


@router.get("/contract-bars", response_model=ContractBarsOut)
def contract_bars(
    contract_id: str, tf: Tf = "1m", from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
) -> ContractBarsOut:  # fmt: skip
    with get_engine().connect() as c:
        if get_instrument(c, contract_id) is None:
            raise HTTPException(404, "unknown contract")
        cov = dbo.coverage(c, contract_id)
        page = (
            chart.bars_page(c, contract_id, tf, from_, to, 5000, None, Calendar.load())
            if cov["n_bars"]
            else None
        )
        ot, ov = dbo.oi_series(c, contract_id, from_, to)
    return ContractBarsOut(
        contract_id=contract_id, bars=None if page is None else BarsOut(**page.__dict__),
        oi=OiOut(t=ot, v=ov), coverage=cov,
    )  # fmt: skip
