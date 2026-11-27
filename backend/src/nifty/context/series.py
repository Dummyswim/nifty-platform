"""Per-minute context state for one session. State at minute m uses only data keyed <= m."""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TypedDict

from nifty.context import vol, writing
from nifty.context.params import ContextParams
from nifty.context.vol import Verdict
from nifty.context.writing import Leg
from nifty.options.bs import implied_vol, years_to_expiry
from nifty.options.chain import atm, strike_step
from nifty.timeutil import to_ist

NA_RATE = "IV n/a: set rate in Settings"
NOTE_FIRST_TICK = "writing since first tick"
NOTE_EXPIRY_DAY = "expiry day: next weekly"
_BAR = timedelta(seconds=60)
_VIX_MIN = 200  # same minimum as vol.vix_rank


@dataclass(frozen=True)
class OptSeries:
    strike: float
    is_call: bool
    expiry: date
    close: dict[datetime, float]  # keyed by 1m bar start UTC
    oi: dict[datetime, float]
    prev_close: float | None  # previous session's last values
    prev_oi: float | None


@dataclass(frozen=True)
class DayInputs:
    day: date
    minutes: list[datetime]  # session 1m bar starts (UTC), closed only
    spot: dict[datetime, float]
    prev_spot_close: float | None
    vix: dict[datetime, float]
    vix_prior_closes: list[float]
    own_iv: dict[tuple[str, bool], float]  # ("weekly", is_call) -> median ATM IV; missing = n/a
    rv: float | None
    r: float | None
    max_stale_s: float
    expiries: list[date]  # listed weekly expiries, sorted
    options: list[OptSeries]
    window_steps: int  # recorded strike window, steps either side of ATM


class Side(TypedDict):
    iv: float | None
    verdict: str | None
    own_iv: float | None
    note: str | None


class State(TypedDict):
    t: int
    vix: float | None
    vix_rank: float | None
    vix_high: bool | None
    ce: Side
    pe: Side
    rv: float | None
    straddle_prem: float | None
    fair_straddle_prem: float | None
    w_day: float | None
    w_roll: float | None
    oi_ce: float | None
    oi_pe: float | None
    one_sided: int | None
    candidate: str
    bias: str
    bias_since: int | None
    exp_move_pts: float | None
    day_move_pts: float | None
    na_reason: str | None


def choose_expiry(day: date, expiries: Sequence[date]) -> date | None:
    """Nearest listed expiry on/after day; on the expiry day itself the next one."""
    later = [e for e in sorted(expiries) if e >= day]
    if later and later[0] == day:
        later = later[1:]
    return later[0] if later else None


def atm_side_iv(
    spot: float, closes_by_strike: dict[float, float], expiry: date, at: datetime, r: float,
    is_call: bool,
) -> float | None:  # fmt: skip
    """IV (vol points) at spot, interpolated between the two strikes bracketing it."""
    lo = max((k for k in closes_by_strike if k <= spot), default=None)
    hi = min((k for k in closes_by_strike if k >= spot), default=None)
    if lo is None or hi is None:
        return None
    t = years_to_expiry(expiry, at)
    iv_lo = implied_vol(closes_by_strike[lo], spot, lo, t, r, is_call)
    iv_hi = implied_vol(closes_by_strike[hi], spot, hi, t, r, is_call)
    if iv_lo is None or iv_hi is None:
        return None
    return vol.interp_iv(spot, (lo, iv_lo * 100.0), (hi, iv_hi * 100.0))


class _Track:
    """Sorted view of one keyed series with stale-limited carry-forward."""

    def __init__(self, data: dict[datetime, float]) -> None:
        self.keys = sorted(data)
        self.vals = [data[k] for k in self.keys]

    def at(self, m: datetime, max_stale_s: float) -> float | None:
        i = bisect_right(self.keys, m) - 1
        if i < 0 or (m - self.keys[i]).total_seconds() > max_stale_s:
            return None
        return self.vals[i]

    def first(self, m: datetime) -> float | None:
        return self.vals[0] if self.keys and self.keys[0] <= m else None

    def before_data(self, m: datetime) -> bool:
        return not self.keys or m < self.keys[0]


@dataclass
class _Carry:
    verdict: dict[bool, Verdict | None] = field(default_factory=lambda: {True: None, False: None})
    vix_high: bool = False
    bias: str = "NONE"
    since: int | None = None
    run_cand: str = "NONE"
    run: int = 0
    miss: int = 0


def _no_expiry_reason(day: date, expiries: Sequence[date]) -> str:
    return "expiry day: next weekly not recorded" if day in expiries else "no listed weekly expiry"


def _legs(
    opts: list[tuple[OptSeries, _Track, _Track]], m: datetime, inp: DayInputs, roll_min: int,
) -> tuple[list[Leg], list[Leg], dict[tuple[float, bool], float], bool]:  # fmt: skip
    """(day legs, rolling legs, closes by (strike, is_call), used a first-tick baseline)."""
    day_legs: list[Leg] = []
    roll_legs: list[Leg] = []
    closes: dict[tuple[float, bool], float] = {}
    first_tick = False
    r_at = m - timedelta(minutes=roll_min)
    for o, c_tr, oi_tr in opts:
        c, oi = c_tr.at(m, inp.max_stale_s), oi_tr.at(m, inp.max_stale_s)
        if c is None:
            continue
        closes[(o.strike, o.is_call)] = c  # IV/straddle need only a fresh close
        if oi is None:
            continue
        prem_base = o.prev_close if o.prev_close is not None else c_tr.first(m)
        oi_base = o.prev_oi if o.prev_oi is not None else oi_tr.first(m)
        first_tick |= o.prev_close is None or o.prev_oi is None
        assert prem_base is not None and oi_base is not None  # a carried value implies a first
        day_legs.append(Leg(o.is_call, oi, c, oi_base, prem_base))
        rc = c_tr.first(m) if c_tr.before_data(r_at) else c_tr.at(r_at, inp.max_stale_s)
        roi = oi_tr.first(m) if oi_tr.before_data(r_at) else oi_tr.at(r_at, inp.max_stale_s)
        if rc is not None and roi is not None:
            roll_legs.append(Leg(o.is_call, oi, c, roi, rc))
    return day_legs, roll_legs, closes, first_tick


def _side_note(iv: float | None, own: float | None, vix_m: float | None, rv: float | None,
               p: ContextParams) -> str | None:  # fmt: skip
    if iv is None:
        return None
    notes = []
    if (
        own is not None
        and vix_m is not None
        and iv > own + vol.band(vix_m, p.band_pct, p.band_floor)
    ):
        notes.append("IV rich vs own 5-day")
    if rv is not None and iv < rv:
        notes.append("IV < RV")
    return "; ".join(notes) or None


def _advance_bias(c: _Carry, cand: str, gated: bool, t: int, p: ContextParams) -> None:
    if c.bias != "NONE":
        c.miss = 0 if cand == c.bias else c.miss + 1
        if c.miss >= p.release:
            c.bias, c.since, c.miss, c.run, c.run_cand = "NONE", None, 0, 0, "NONE"
        return
    if gated or cand == "NONE":
        c.run, c.run_cand = 0, "NONE"
        return
    c.run = c.run + 1 if cand == c.run_cand else 1
    c.run_cand = cand
    if c.run >= p.confirm:
        c.bias, c.since, c.miss = cand, t, 0


def build_series(inp: DayInputs, p: ContextParams) -> tuple[date | None, list[State], list[str]]:
    """(expiry used, one State per minute, notes)."""
    expiry = choose_expiry(inp.day, inp.expiries)
    notes: list[str] = [NOTE_EXPIRY_DAY] if expiry is not None and inp.day in inp.expiries else []
    opts = [(o, _Track(o.close), _Track(o.oi)) for o in inp.options if o.expiry == expiry]
    strikes = sorted({o.strike for o in inp.options if o.expiry == expiry})
    step = strike_step(strikes)
    n_steps = min(p.strikes, inp.window_steps)
    spot_tr, vix_tr = _Track(inp.spot), _Track(inp.vix)
    not_before = time.fromisoformat(p.not_before)
    carry = _Carry()
    out: list[State] = []
    for m in inp.minutes:
        t = int(m.timestamp())
        spot_m, vix_m = spot_tr.at(m, inp.max_stale_s), vix_tr.at(m, inp.max_stale_s)
        rank = vol.vix_rank(inp.vix_prior_closes, vix_m) if vix_m is not None else None
        if rank is None:
            carry.vix_high = False
        elif rank >= p.vix_pct:
            carry.vix_high = True
        elif rank < p.vix_exit_pct:
            carry.vix_high = False
        vix_high = carry.vix_high if rank is not None else None

        day_legs: list[Leg] = []
        roll_legs: list[Leg] = []
        closes: dict[tuple[float, bool], float] = {}
        atm_k = atm(spot_m, strikes) if spot_m is not None else None
        if expiry is not None and atm_k is not None and step is not None:
            span = n_steps * step + 1e-6
            in_play = [x for x in opts if abs(x[0].strike - atm_k) <= span]
            day_legs, roll_legs, closes, first_tick = _legs(in_play, m, inp, p.roll_min)
            if first_tick and NOTE_FIRST_TICK not in notes:
                notes.append(NOTE_FIRST_TICK)

        ivs: dict[bool, float | None] = {True: None, False: None}
        if expiry is not None and spot_m is not None and inp.r is not None:
            for is_call in (True, False):
                side = {k: c for (k, call), c in closes.items() if call == is_call}
                ivs[is_call] = atm_side_iv(spot_m, side, expiry, m + _BAR, inp.r, is_call)

        if expiry is None:
            na: str | None = _no_expiry_reason(inp.day, inp.expiries)
        elif inp.r is None:
            na = NA_RATE
        elif len(inp.vix_prior_closes) < _VIX_MIN:
            na = "VIX history short"
        elif vix_m is None:
            na = "no VIX data"
        elif spot_m is None:
            na = "no spot data"
        elif not day_legs or (ivs[True] is None and ivs[False] is None):
            na = "no option data"
        else:
            na = None

        sides: dict[bool, Side] = {}
        for is_call in (True, False):
            iv = ivs[is_call]
            v = (
                vol.verdict(iv, vix_m, carry.verdict[is_call], p)
                if iv is not None and vix_m is not None
                else None
            )
            carry.verdict[is_call] = v if na is None else None
            own = inp.own_iv.get(("weekly", is_call))
            sides[is_call] = Side(iv=iv, verdict=v, own_iv=own,
                                  note=_side_note(iv, own, vix_m, inp.rv, p))  # fmt: skip

        w_day = writing.score(day_legs) if day_legs else None
        w_roll = writing.score(roll_legs) if day_legs else None
        oi_ce, oi_pe = writing.raw_oi(day_legs) if day_legs else (None, None)
        os_: int | None = None
        cand = "NONE"
        if w_day is not None and w_roll is not None:
            os_ = writing.one_sided(w_day, w_roll, p.w_min)
            # a shown bias holds while writing stays beyond the lower exit threshold
            held = writing.one_sided(w_day, w_roll, p.w_exit)
            shown = {"BEARISH": -1, "BULLISH": 1}.get(carry.bias)
            direction = held if held == shown else os_
            if na is None and vix_high:
                if direction == -1 and sides[False]["verdict"] in ("FAIR", "CHEAP"):
                    cand = "BEARISH"
                elif direction == 1 and sides[True]["verdict"] in ("FAIR", "CHEAP"):
                    cand = "BULLISH"
        _advance_bias(carry, cand, to_ist(m).time() < not_before, t, p)

        straddle = None
        if atm_k is not None and (atm_k, True) in closes and (atm_k, False) in closes:
            straddle = closes[(atm_k, True)] + closes[(atm_k, False)]
        fair = None
        if expiry is not None and spot_m is not None and vix_m is not None:
            fair = vol.fair_straddle_prem(spot_m, vix_m, years_to_expiry(expiry, m + _BAR))
        vix_open = vix_tr.first(m)
        prev = inp.prev_spot_close
        exp_move = None
        if prev is not None and vix_open is not None:
            exp_move = vol.expected_move_pts(prev, vix_open)
        out.append(State(
            t=t, vix=vix_m, vix_rank=rank, vix_high=vix_high, ce=sides[True], pe=sides[False],
            rv=inp.rv, straddle_prem=straddle, fair_straddle_prem=fair, w_day=w_day, w_roll=w_roll,
            oi_ce=oi_ce, oi_pe=oi_pe, one_sided=os_, candidate=cand, bias=carry.bias,
            bias_since=carry.since,
            exp_move_pts=exp_move,
            day_move_pts=spot_m - prev if prev is not None and spot_m is not None else None,
            na_reason=na,
        ))  # fmt: skip
    return expiry, out, notes
