"""Pure options maths and mapping: Black-Scholes known answers, chain logic, recording window, paper trades."""

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from nifty.contracts import Instrument, TradeRecord
from nifty.contracts.units import Inr, Prem, UnitMismatch
from nifty.options.bs import bs, effective_today, implied_vol, years_to_expiry
from nifty.options.chain import (
    DEFAULT_OFFSETS,
    STRIKE_TYPES,
    atm,
    expiry_kinds,
    strike_for,
    strike_step,
)  # fmt: skip
from nifty.options.paper import Policy, Quote, map_trade, pick_contract
from nifty.options.window import choose_contracts, needs_recentre
from nifty.timeutil import IST


# ---- Black-Scholes -------------------------------------------------------------------------------
def test_black_scholes_known_answers() -> None:
    c = bs(100, 100, 1.0, 0.05, 0.2, True)
    p = bs(100, 100, 1.0, 0.05, 0.2, False)
    assert c is not None and p is not None
    assert c.price == pytest.approx(10.4506, abs=1e-4) and p.price == pytest.approx(
        5.5735, abs=1e-4
    )
    assert c.delta == pytest.approx(0.6368, abs=1e-4) and p.delta == pytest.approx(
        0.6368 - 1, abs=1e-4
    )
    assert c.gamma == pytest.approx(0.018762, abs=1e-5) == p.gamma
    assert c.vega_1pct == pytest.approx(0.37524, abs=1e-4)  # vega 37.524 per 1.0 vol / 100
    assert c.theta_day == pytest.approx(-6.414 / 365, abs=2e-4)  # annual theta -6.414


def test_put_call_parity_and_iv_round_trip() -> None:
    s, k, t, r = 25_000.0, 25_100.0, 0.05, 0.07
    c, p = bs(s, k, t, r, 0.15, True), bs(s, k, t, r, 0.15, False)
    assert c is not None and p is not None
    assert c.price - p.price == pytest.approx(
        s - k * math.exp(-r * t), abs=1e-8
    )  # C - P = S - K e^{-rT}
    for sigma in (0.08, 0.15, 0.45):
        for call in (True, False):
            g = bs(s, k, t, r, sigma, call)
            assert g is not None
            assert implied_vol(g.price, s, k, t, r, call) == pytest.approx(sigma, abs=1e-5)
    assert implied_vol(0.0, s, k, t, r, True) is None  # no price
    assert (
        implied_vol(1.0, 25_000, 20_000, t, r, True) is None
    )  # below intrinsic: not a valid quote
    assert bs(100, 100, 0.0, 0.05, 0.2, True) is None and bs(100, 100, 1.0, 0.05, 0.0, True) is None


def test_time_to_expiry_runs_to_1530_ist_of_the_expiry() -> None:
    exp = date(2026, 11, 24)
    now = datetime(2026, 11, 24, 9, 30, tzinfo=IST)
    assert years_to_expiry(exp, now) == pytest.approx(6 * 3600 / (365 * 86400))
    assert years_to_expiry(exp, datetime(2026, 11, 24, 16, 0, tzinfo=IST)) == 0.0
    assert effective_today(datetime(2026, 11, 24, 15, 29, tzinfo=IST)) == date(2026, 11, 24)
    assert effective_today(datetime(2026, 11, 24, 15, 30, tzinfo=IST)) == date(2026, 11, 25)


# ---- chain ---------------------------------------------------------------------------------------
def test_strike_step_is_the_modal_gap_and_never_hardcoded() -> None:
    assert strike_step([100, 150, 200, 250]) == 50
    assert (
        strike_step([24_900, 24_950, 25_000, 25_100, 25_150, 25_200]) == 50
    )  # one 100 gap is not the mode
    assert strike_step([100, 125, 150, 200, 225]) == 25
    assert strike_step([100, 200, 300, 350, 400, 450]) == 50 and strike_step([5]) is None
    assert strike_step([100, 200, 250, 300, 400]) == 50  # 2 gaps of 100 vs 2 of 50: the smaller


def test_atm_is_the_nearest_listed_strike_and_ties_go_down() -> None:
    ks = [24_900, 24_950, 25_000, 25_050]
    assert atm(24_980, ks) == 25_000 and atm(24_974.9, ks) == 24_950
    assert atm(24_975, ks) == 24_950  # exact tie: lower
    assert atm(1, ks) == 24_900 and atm(99_999, ks) == 25_050 and atm(1, []) is None


def test_strike_types_for_calls_and_puts() -> None:
    listed = [24_700 + 50 * i for i in range(13)]  # 24700 .. 25300
    a = 25_000.0
    ce = {t: strike_for(t, "CE", a, 50, listed) for t in STRIKE_TYPES}
    pe = {t: strike_for(t, "PE", a, 50, listed) for t in STRIKE_TYPES}
    assert ce == {
        "Deep ITM": 24_750,
        "ITM": 24_900,
        "ATM": 25_000,
        "OTM": 25_100,
        "Deep OTM": 25_250,
    }
    assert pe == {
        "Deep ITM": 25_250,
        "ITM": 25_100,
        "ATM": 25_000,
        "OTM": 24_900,
        "Deep OTM": 24_750,
    }
    assert (
        strike_for("ITM", "CE", a, 50, listed, {**DEFAULT_OFFSETS, "ITM": 3}) == 24_850
    )  # editable offsets
    assert (
        strike_for("Deep ITM", "CE", 24_750, 50, listed) is None
    )  # 24500 is not listed: unavailable


def test_expiry_kinds_come_from_the_master_only() -> None:
    ex = [
        date(2026, 11, 24),
        date(2026, 12, 1),
        date(2026, 12, 8),
        date(2026, 12, 29),
        date(2027, 1, 26),
    ]
    k = expiry_kinds(ex, date(2026, 11, 20))
    assert k == {
        "current weekly": date(2026, 11, 24),
        "next weekly": date(2026, 12, 1),
        "monthly": date(2026, 11, 24),
    }
    k2 = expiry_kinds(ex, date(2026, 11, 25))  # the Nov expiry is gone
    assert k2["current weekly"] == date(2026, 12, 1) and k2["next weekly"] == date(2026, 12, 8)
    assert k2["monthly"] == date(2026, 12, 29)  # last listed expiry of December
    one = expiry_kinds([date(2026, 11, 24)], date(2026, 11, 24))  # expiry day itself still counts
    assert one == {
        "current weekly": date(2026, 11, 24),
        "next weekly": None,
        "monthly": date(2026, 11, 24),
    }
    assert expiry_kinds([], date(2026, 11, 24)) == {
        "current weekly": None,
        "next weekly": None,
        "monthly": None,
    }


# ---- recording window ----------------------------------------------------------------------------
def opt(exp: date, k: float, t: str, token: int = 1, lot: int = 75) -> Instrument:
    return Instrument(
        instrument_id=f"kite:NFO:N{exp:%y%m%d}{int(k)}{t}", provider="kite", provider_token=token,
        exchange="NFO", instrument_type=t, tradingsymbol=f"N{exp:%y%m%d}{int(k)}{t}",  # type: ignore[arg-type]
        underlying="NIFTY", expiry=exp, strike=k, option_type=t, tick_size=0.05, lot_size=lot,  # type: ignore[arg-type]
    )  # fmt: skip


E1, E2 = date(2026, 11, 24), date(2026, 12, 1)


def book() -> list[Instrument]:
    return [
        opt(e, 24_500 + 50 * i, t, token=1000 + i)
        for e in (E1, E2)
        for i in range(21)
        for t in ("CE", "PE")
    ]


def test_window_is_atm_plus_minus_n_steps_for_the_chosen_expiries_and_recentres_on_a_move() -> None:
    got = choose_contracts(book(), [E1], 25_000.0, 50, 5)
    assert len(got) == 22 and {o.strike for o in got} == {24_750 + 50 * i for i in range(11)}
    assert {o.option_type for o in got} == {"CE", "PE"} and {o.expiry for o in got} == {E1}
    assert len(choose_contracts(book(), [E1, E2], 25_000.0, 50, 5)) == 44
    assert len(choose_contracts(book(), [E1, E2], 25_000.0, 50, 5, limit=10)) == 10  # hard cap
    assert [
        o.strike for o in choose_contracts(book(), [E1], 24_500.0, 50, 2) if o.option_type == "CE"
    ] == [24_500, 24_550, 24_600]
    assert (
        not needs_recentre(25_000, 25_000)
        and needs_recentre(25_000, 25_050)
        and needs_recentre(None, 25_000)
    )
    assert not needs_recentre(25_000, None)


# ---- paper mapping ---------------------------------------------------------------------------------
T_IN = datetime(2026, 11, 23, 5, 0, tzinfo=UTC)  # 10:30 IST, a day before E1
T_OUT = T_IN + timedelta(minutes=20)


def trade(side: str = "long", reason: str = "TP", entry_px: float = 25_020.0) -> TradeRecord:
    return TradeRecord(
        trade_id="t1", engine_id="e", instrument_id="i", side=side, entry_time=T_IN, entry_px=entry_px,  # type: ignore[arg-type]
        exit_time=T_OUT, exit_px=entry_px + 30, exit_reason=reason, gross_pts=30, net_pts=29,
    )  # fmt: skip


class Book:
    def __init__(self, q: dict[str, list[Quote]]) -> None:
        self.q = q

    def last_quote(self, contract_id: str, at: datetime) -> Quote | None:
        ok = [x for x in self.q.get(contract_id, []) if x.ts <= at]
        return max(ok, key=lambda x: x.ts, default=None)


def quotes(cid: str, ask: float = 100.0, bid: float = 90.0, out_bid: float = 130.0) -> Book:
    return Book(
        {
            cid: [
                Quote(T_IN - timedelta(seconds=10), bid, ask),
                Quote(T_OUT - timedelta(seconds=5), out_bid, 140.0),
            ]
        }
    )


def test_contract_is_chosen_at_entry_time_from_strike_type_and_expiry_policy() -> None:
    c = pick_contract(
        book(), True, 25_020.0, T_IN, Policy()
    )  # BUY -> CE, ATM of 25020 = 25000, current weekly
    assert (c.option_type, c.strike, c.expiry) == ("CE", 25_000, E1)  # type: ignore[union-attr]
    c2 = pick_contract(
        book(), False, 25_020.0, T_IN, Policy(strike_type="ITM", expiry_kind="next weekly")
    )
    assert (c2.option_type, c2.strike, c2.expiry) == ("PE", 25_100, E2)  # type: ignore[union-attr]  # PE ITM = higher
    assert pick_contract(book(), True, 25_020.0, T_IN, Policy(expiry_kind="monthly")) is not None
    assert (
        pick_contract(
            book(),
            True,
            25_020.0,
            T_IN,
            Policy(strike_type="Deep OTM"),
            {**DEFAULT_OFFSETS, "Deep OTM": 99},
        )
        is None
    )


def test_entry_at_the_ask_exit_at_the_bid_lot_arithmetic_and_synthetic_flag() -> None:
    cid = pick_contract(book(), True, 25_020.0, T_IN, Policy()).instrument_id  # type: ignore[union-attr]
    mapped, why = map_trade(trade(), book(), quotes(cid), Policy(lots=2, cost_inr=100.0))
    assert why is None and mapped is not None
    assert (mapped.contract_id, mapped.entry_prem, mapped.exit_prem) == (
        cid,
        100.0,
        130.0,
    )  # ask in, bid out
    # (130 - 100) * 2 lots * 75 - 100 = 4400; roi on the premium outlay 100 * 150 = 15000
    assert mapped.pnl_inr == 4_400.0 and mapped.roi_pct == pytest.approx(4_400 / 15_000 * 100)
    assert (
        mapped.synthetic is True and "option_paper" in mapped.flags and mapped.net_pts == 29
    )  # index fields intact
    clock, _ = map_trade(trade(reason="EOD"), book(), quotes(cid), Policy())
    assert clock is not None and clock.synthetic is False  # a clock exit is not index-triggered
    pe = pick_contract(book(), False, 25_020.0, T_IN, Policy())
    assert pe is not None
    short, _ = map_trade(trade("short"), book(), quotes(pe.instrument_id), Policy())
    assert short is not None and short.contract_id is not None
    assert short.contract_id.endswith("PE")


def test_stale_or_missing_quotes_skip_the_trade_as_no_quote() -> None:
    cid = pick_contract(book(), True, 25_020.0, T_IN, Policy()).instrument_id  # type: ignore[union-attr]
    stale = Book(
        {
            cid: [
                Quote(T_IN - timedelta(seconds=61), 90, 100),
                Quote(T_OUT - timedelta(seconds=5), 130, 140),
            ]
        }
    )
    assert map_trade(trade(), book(), stale, Policy()) == (None, "no_quote")  # 61 s > 60 s
    assert (
        map_trade(trade(), book(), stale, Policy(max_stale_s=120))[0] is not None
    )  # the limit is a pref
    assert map_trade(trade(), book(), Book({}), Policy()) == (
        None,
        "no_quote",
    )  # never reconstructed
    no_ask = Book({cid: [Quote(T_IN, 90, None), Quote(T_OUT, 130, 140)]})
    assert map_trade(trade(), book(), no_ask, Policy()) == (None, "no_quote")
    assert map_trade(trade(), [], Book({}), Policy()) == (None, "no_contract")
    no_lot = [opt(E1, 25_000, "CE", lot=0)]
    assert map_trade(trade(), no_lot, quotes(no_lot[0].instrument_id), Policy()) == (
        None,
        "no_contract",
    )


def test_units_never_mix() -> None:
    with pytest.raises(UnitMismatch):
        Prem(1.0) - Inr(1.0)
    with pytest.raises(UnitMismatch):
        Inr(5.0) + Prem(1.0)
    assert isinstance(Prem(2.0) - Prem(1.0), Prem) and isinstance(Inr(2.0) - Inr(1.0), Inr)


def test_window_planner_recentres_only_when_the_atm_strike_moves() -> None:
    from nifty.options.window import WindowPlanner

    pl = WindowPlanner(book(), [E1], window_steps=2)
    first = pl.update(25_010.0)  # ATM 25000: window 24900..25100, CE + PE
    assert first is not None and len(first[0]) == 10 and first[1] == []
    assert (
        pl.update(25_020.0) is None and pl.update(24_980.0) is None
    )  # still ATM 25000 (no move of a step)
    moved = pl.update(25_060.0)  # ATM 25050: 25150 enters, 24900 leaves (CE and PE)
    assert moved is not None
    assert sorted((o.strike, o.option_type) for o in moved[0]) == [(25_150, "CE"), (25_150, "PE")]
    assert sorted((o.strike, o.option_type) for o in moved[1]) == [(24_900, "CE"), (24_900, "PE")]
    assert len(pl.current) == 10 and pl.atm == 25_050


def test_planner_without_listed_contracts_does_nothing() -> None:
    from nifty.options.window import WindowPlanner

    assert WindowPlanner([], [E1]).update(25_000.0) is None
    assert WindowPlanner(book(), []).update(25_000.0) is None
