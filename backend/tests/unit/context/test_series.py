import time as clock
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

import pytest

from nifty.context.params import ContextParams
from nifty.context.series import DayInputs, OptSeries, build_series, choose_expiry
from nifty.options.bs import bs, years_to_expiry
from nifty.timeutil import IST

DAY = date(2026, 11, 24)
EXP = date(2026, 11, 26)
STRIKES = [25700.0 + 50 * j for j in range(13)]
P = ContextParams()
P_OI = ContextParams(writing="oi")
T0 = datetime(2026, 11, 24, 9, 15, tzinfo=IST).astimezone(UTC)
MINUTES = [T0 + timedelta(minutes=i) for i in range(40)]
PREV_CLOSE_AT = datetime(2026, 11, 23, 15, 30, tzinfo=IST).astimezone(UTC)
PREV_SPOT = 25950.0


def call_writing(i: int, k: float) -> float:
    return 1000.0 + 100 * i if i >= 1 else 1000.0


def flat(i: int, k: float) -> float:
    return 1000.0


def falling_iv(i: int) -> float:  # written leg: IV eases off all day
    return 18.0 - 0.01 * i


def flat_iv(i: int) -> float:
    return 18.0


def make_day(
    *,
    spot: Callable[[int], float] = lambda i: 26000.0,
    ce_iv: Callable[[int], float] = falling_iv,
    pe_iv: Callable[[int], float] = flat_iv,
    base_iv: float | None = 18.5,
    ce_oi: Callable[[int, float], float] = call_writing,
    pe_oi: Callable[[int, float], float] = flat,
    alive: Callable[[int, float, bool], bool] = lambda i, k, c: True,
    oi_alive: Callable[[int, float, bool], bool] = lambda i, k, c: True,
    vix: Callable[[int], float] = lambda i: 18.0,
    prev_oi: float | None = 1000.0,
    r: float | None = 0.065,
    n_prior: int = 252,
    day: date = DAY,
    expiries: tuple[date, ...] = (EXP,),
    expiry: date = EXP,
    minutes: list[datetime] = MINUTES,
    strikes: list[float] = STRIKES,
) -> DayInputs:
    """40-minute day from 09:15 IST, VIX 18, options priced from bs() at the given IVs per
    minute; previous close priced at `base_iv` at the previous session's close (None = none)."""
    options = []
    for k in strikes:
        for is_call, iv_fn, oi_fn in ((True, ce_iv, ce_oi), (False, pe_iv, pe_oi)):
            close: dict[datetime, float] = {}
            oi: dict[datetime, float] = {}
            prev_close = None
            if base_iv is not None:
                g0 = bs(PREV_SPOT, k, years_to_expiry(expiry, PREV_CLOSE_AT), 0.065,
                        base_iv / 100.0, is_call)  # fmt: skip
                assert g0 is not None
                prev_close = g0.price
            for i, m in enumerate(minutes):
                g = bs(spot(i), k, years_to_expiry(expiry, m + timedelta(seconds=60)), 0.065,
                       iv_fn(i) / 100.0, is_call)  # fmt: skip
                assert g is not None
                if alive(i, k, is_call):
                    close[m] = g.price
                    if oi_alive(i, k, is_call):
                        oi[m] = oi_fn(i, k)
            options.append(OptSeries(k, is_call, expiry, close, oi, prev_close, prev_oi))
    return DayInputs(
        day=day,
        minutes=list(minutes),
        spot={m: spot(i) for i, m in enumerate(minutes)},
        prev_spot_close=PREV_SPOT,
        prev_session_close_at=PREV_CLOSE_AT,
        vix={m: vix(i) for i, m in enumerate(minutes)},
        vix_prior_closes=[10 + 10 * j / (n_prior - 1) for j in range(n_prior)],
        own_iv={("weekly", True): 17.5},
        rv=12.0,
        r=r,
        max_stale_s=120,
        expiries=list(expiries),
        options=options,
        window_steps=5,
    )


def idx(hh: int, mm: int) -> int:
    return (hh - 9) * 60 + mm - 15


def test_choose_expiry() -> None:
    assert choose_expiry(DAY, [EXP, EXP + timedelta(7)]) == EXP
    assert choose_expiry(EXP, [EXP, EXP + timedelta(7)]) == EXP + timedelta(7)
    assert choose_expiry(EXP, [EXP]) is None
    assert choose_expiry(DAY, []) is None


def test_bearish_after_confirm() -> None:
    expiry, s, notes = build_series(make_day(), P)
    assert expiry == EXP and notes == [] and all(x["flags"] == [] for x in s)
    assert s[idx(9, 16)]["candidate"] == "BEARISH"
    assert s[idx(9, 31)]["bias"] == "NONE"
    first = idx(9, 32)
    assert s[first]["bias"] == "BEARISH"
    assert s[first]["bias_since"] == int(MINUTES[first].timestamp())
    assert all(x["bias"] == "BEARISH" and x["bias_since"] == s[first]["t"] for x in s[first:])
    x = s[first]
    assert x["pe"]["iv"] == pytest.approx(18.0, abs=0.05)
    assert x["ce"]["iv"] == pytest.approx(falling_iv(first), abs=0.05)
    assert x["writing"] == "iv"
    assert x["pe"]["verdict"] == "FAIR" and x["vix_high"] is True and x["one_sided"] == -1
    assert x["ce"]["own_iv"] == 17.5 and x["ce"]["note"] is None and x["pe"]["own_iv"] is None
    assert x["w_day"] == -1.0 and x["oi_pe"] == 0.0 and x["na_reason"] is None
    assert x["straddle_prem"] is not None and x["fair_straddle_prem"] is not None
    assert x["day_move_pts"] == 50.0 and x["exp_move_pts"] == pytest.approx(25950 * 0.18 / 252**0.5)


def test_no_bias_before_0930() -> None:
    _, s, _ = build_series(make_day(), P)
    early = [x for x, m in zip(s, MINUTES, strict=True) if m.astimezone(IST).time() < P_930]
    assert len(early) == 15 and all(x["bias"] == "NONE" for x in early)


P_930 = datetime(2026, 1, 1, 9, 30).time()


def test_rich_put_blocks_bearish() -> None:
    _, s, _ = build_series(make_day(pe_iv=lambda i: 21.0), P)
    assert all(x["pe"]["verdict"] == "RICH" for x in s)
    assert all(x["candidate"] == "NONE" and x["bias"] == "NONE" for x in s)


def test_release_after_two() -> None:
    k = idx(9, 45)

    def until_k(i: int, strike: float) -> float:
        return call_writing(i, strike) if i < k else 1000.0

    _, s, _ = build_series(make_day(ce_oi=until_k), P)
    assert s[k - 1]["bias"] == "BEARISH"
    assert s[k]["candidate"] == "NONE" and s[k]["bias"] == "BEARISH"
    assert s[k + 1]["bias"] == "NONE" and s[k + 1]["bias_since"] is None


def test_series_atm_switch_no_bias_flip() -> None:
    k = idx(9, 40)

    def ce(i: int, strike: float) -> float:  # 26200 enters play at k unwinding, not writing
        return 1000.0 - 10 * i if strike == 26200 else call_writing(i, strike)

    def spot(i: int) -> float:
        return 26000.0 if i < k else 26030.0

    _, s, _ = build_series(make_day(spot=spot, ce_oi=ce), P)
    since = s[idx(9, 32)]["bias_since"]
    assert all(x["bias"] == "BEARISH" and x["bias_since"] == since for x in s[idx(9, 32) :])
    assert s[k]["pe"]["iv"] == pytest.approx(18.0, abs=0.05)
    assert s[k - 1]["oi_ce"] == 7 * 2400  # 25850..26150
    assert s[k]["oi_ce"] == 6 * 2500 - 250  # 25900..26200: 25850 left, 26200 entered
    t = years_to_expiry(EXP, MINUTES[k] + timedelta(seconds=60))
    legs = [bs(26030.0, 26050.0, t, 0.065, iv / 100, c)
            for c, iv in ((True, falling_iv(k)), (False, 18.0))]  # fmt: skip
    assert s[k]["straddle_prem"] == pytest.approx(sum(g.price for g in legs if g))  # ATM 26050


def test_stale_oi_keeps_iv_and_straddle() -> None:
    _, s, _ = build_series(make_day(oi_alive=lambda i, k, c: i < 20), P)
    x = s[25]
    assert x["w_day"] is None and x["na_reason"] == "no option data"
    assert x["pe"]["iv"] == pytest.approx(18.0, abs=0.05) and x["straddle_prem"] is not None


def test_stale_strike_dropped() -> None:
    def pe_writing(i: int, k: float) -> float:
        return 1000.0 + 50 * i if k == 25900 else 1000.0

    def alive(i: int, k: float, is_call: bool) -> bool:
        return i < 30 and not (k == 25900 and not is_call and i >= 20)

    _, s, _ = build_series(make_day(pe_oi=pe_writing, pe_iv=falling_iv, alive=alive), P)
    assert s[10]["w_day"] == pytest.approx((50 - 700) / 750)
    # PE 25900 last bar at i=19 is 120 s old at i=21: still carried
    assert s[21]["w_day"] == pytest.approx((50 * 19 - 700 * 21) / (50 * 19 + 700 * 21))
    assert s[22]["w_day"] == -1.0  # PE 25900 dropped
    assert s[31]["na_reason"] is None and s[31]["bias"] == "BEARISH"
    assert s[32]["na_reason"] == "no option data" and s[32]["w_day"] is None
    # an n/a minute never carries a bias: released at once
    assert all(x["bias"] == "NONE" and x["bias_since"] is None for x in s[32:])
    assert all(x["candidate"] == "NONE" for x in s[32:])


def test_na_minute_releases_bias_and_needs_fresh_confirm() -> None:
    k = idx(9, 36)  # one minute with no VIX while BEARISH is shown
    inp = make_day()
    gone = inp.minutes[k]
    inp.vix.pop(gone)
    inp = DayInputs(**{**inp.__dict__, "max_stale_s": 30})  # the gap is not carried
    _, s, _ = build_series(inp, P)
    assert s[k - 1]["bias"] == "BEARISH" and s[k]["na_reason"] == "no VIX data"
    assert s[k]["bias"] == "NONE" and s[k]["bias_since"] is None
    # a new bias needs `confirm` fresh minutes after the gap
    assert [x["bias"] for x in s[k + 1 : k + 4]] == ["NONE", "NONE", "BEARISH"]
    assert s[k + 3]["bias_since"] == s[k + 3]["t"]


def test_baseline_fallback_first_tick() -> None:
    _, s, notes = build_series(make_day(prev_oi=None, base_iv=None), P)
    assert notes == []
    assert all(x["flags"] == ["writing since first tick"] for x in s)
    assert s[idx(9, 32)]["bias"] == "BEARISH"


def test_first_tick_flag_only_on_minutes_using_it() -> None:
    # the only first-tick legs (no prior OI) are strikes far from ATM that enter play at k
    k = idx(9, 40)
    inp = make_day(spot=lambda i: 26000.0 if i < k else 26300.0)
    far = {o.strike for o in inp.options if o.strike > 26150}
    opts = [OptSeries(o.strike, o.is_call, o.expiry, o.close, o.oi, o.prev_close,
                      None if o.strike in far else o.prev_oi) for o in inp.options]  # fmt: skip
    _, s, notes = build_series(DayInputs(**{**inp.__dict__, "options": opts}), P)
    assert notes == []
    assert all(x["flags"] == [] for x in s[:k])
    assert all(x["flags"] == ["writing since first tick"] for x in s[k:])


def test_expiry_day_uses_next_weekly() -> None:
    expiry, s, notes = build_series(make_day(day=DAY, expiries=(DAY, EXP)), P)
    assert expiry == EXP and notes == []
    assert all(x["flags"] == ["expiry day: next weekly"] for x in s)
    assert s[idx(9, 32)]["bias"] == "BEARISH"


def test_expiry_day_next_weekly_missing() -> None:
    expiry, s, _ = build_series(make_day(expiries=(DAY,)), P)
    assert expiry is None
    assert all("expiry" in (x["na_reason"] or "") and x["bias"] == "NONE" for x in s)


def test_rate_missing() -> None:
    _, s, _ = build_series(make_day(r=None), P)
    assert all(x["ce"]["iv"] is None and x["pe"]["iv"] is None for x in s)
    assert all(x["na_reason"] == "IV n/a: set rate in Settings" for x in s)
    assert all(x["bias"] == "NONE" for x in s)


def test_short_vix_history() -> None:
    _, s, _ = build_series(make_day(n_prior=150), P)
    assert all(x["vix_rank"] is None and x["vix_high"] is None and x["bias"] == "NONE" for x in s)
    assert s[0]["na_reason"] == "VIX history short"


def test_no_lookahead() -> None:
    # spot drifts 25990 -> 26038 by the cut (ATM 26000 -> 26050 at i=18); VIX rises 17 -> 18.2
    full = make_day(spot=lambda i: 25990.0 + 2 * i, vix=lambda i: 17.0 + 0.05 * i)
    cut = MINUTES[24]

    def trim(d: dict[datetime, float]) -> dict[datetime, float]:
        return {m: v for m, v in d.items() if m <= cut}

    trunc = DayInputs(**{
        **full.__dict__,
        "minutes": MINUTES[:25],
        "spot": trim(full.spot),
        "vix": trim(full.vix),
        "options": [OptSeries(o.strike, o.is_call, o.expiry, trim(o.close), trim(o.oi),
                              o.prev_close, o.prev_oi) for o in full.options],
    })  # fmt: skip
    assert build_series(trunc, P)[1] == build_series(full, P)[1][:25]


def test_side_notes() -> None:
    _, s, _ = build_series(make_day(ce_iv=lambda i: 20.0), P)
    assert s[20]["ce"]["note"] == "IV rich vs own 5-day"  # 20 > 17.5 + 1.8
    assert s[20]["rv"] == 12.0 and s[20]["pe"]["note"] is None


def test_shown_bias_holds_above_w_exit() -> None:
    k = idx(9, 40)

    def ce(i: int, strike: float) -> float:
        return 1000.0 + 100 * min(i, k) if i >= 1 else 1000.0

    def pe(i: int, strike: float) -> float:
        return 2400.0 if i >= k else 1000.0

    _, s, _ = build_series(make_day(ce_oi=ce, pe_oi=pe, pe_iv=falling_iv), P)
    assert s[k]["w_day"] == pytest.approx((1400 - 2500) / 3900)  # below w_min, above w_exit
    assert s[k]["one_sided"] == 0 and s[k]["candidate"] == "BEARISH"
    assert s[k + 1]["bias"] == "BEARISH"
    assert s[k + 2]["candidate"] == "NONE" and s[k + 2]["bias"] == "BEARISH"  # w_roll turned +
    assert s[k + 3]["bias"] == "NONE"


def falling_spot(i: int) -> float:
    return 26000.0 - 2 * i


def put_writing(i: int, k: float) -> float:
    return 1000.0 + 100 * i


def test_down_day_put_writing_counts_with_iv_rule() -> None:
    # spot falls, so every put gains premium: the old premium rule could never count it
    inp = make_day(spot=falling_spot, ce_oi=flat, pe_oi=put_writing, ce_iv=flat_iv,
                   pe_iv=falling_iv)  # fmt: skip
    _, s, _ = build_series(inp, P)
    assert all(x["writing"] == "iv" for x in s)
    assert all(x["w_day"] == 1.0 and x["w_roll"] == 1.0 for x in s[16:])
    assert s[idx(9, 32)]["bias"] == "BULLISH"


def test_oi_rule_scores_raw_deltas() -> None:
    # puts bought: OI up with put IV above the 18.5 baseline and rising, so the iv rule ignores
    # them and the oi rule counts
    inp = make_day(spot=falling_spot, ce_oi=call_writing, pe_oi=put_writing,
                   pe_iv=lambda i: 18.6 + 0.01 * i)  # fmt: skip
    _, s_oi, _ = build_series(inp, P_OI)
    _, s_iv, _ = build_series(inp, P)
    assert all(x["writing"] == "oi" for x in s_oi)
    for x in s_oi[1:]:
        ce, pe = x["oi_ce"], x["oi_pe"]
        assert ce is not None and pe is not None
        assert x["w_day"] == pytest.approx((pe - ce) / (abs(pe) + abs(ce)))
    assert all(x["w_day"] == -1.0 for x in s_iv[1:])
    assert all(x["w_day"] == 0.0 for x in s_oi[1:])  # equal call and put OI build-up
    # the rest of the state is shared by both rules
    keep = ("vix_rank", "ce", "pe", "straddle_prem", "oi_ce", "oi_pe", "na_reason")
    shared = [[dict(x)[k] for k in keep] for x in s_oi]
    assert shared == [[dict(x)[k] for k in keep] for x in s_iv]


def test_iv_missing_leg_left_out_of_iv_score_only() -> None:
    # no previous close and no spot before 09:20: the day IV baseline falls back to the first
    # IV, which needs spot at the first close; with it missing the leg has no IV baseline
    inp = make_day(base_iv=None)
    early = [m for m in inp.minutes if m < T0 + timedelta(minutes=5)]
    inp = DayInputs(**{**inp.__dict__, "spot": {m: v for m, v in inp.spot.items()
                                               if m not in early}})  # fmt: skip
    _, s_iv, _ = build_series(inp, P)
    _, s_oi, _ = build_series(inp, P_OI)
    x_iv, x_oi = s_iv[20], s_oi[20]
    assert x_iv["na_reason"] is None and x_iv["w_day"] == 0.0  # no IV baseline for any leg
    assert x_oi["w_day"] == -1.0


def test_build_series_is_fast_for_a_full_day() -> None:
    minutes = [T0 + timedelta(minutes=i) for i in range(375)]
    assert minutes[-1].astimezone(IST).time() == time(15, 29)
    strikes = [25850.0 + 50 * j for j in range(7)]
    inp = make_day(minutes=minutes, strikes=strikes, spot=lambda i: 26000.0 + 0.3 * i,
                   ce_iv=lambda i: 18.0 - 0.002 * i)  # fmt: skip
    assert len(inp.options) == 14
    t = clock.perf_counter()
    _, s, _ = build_series(inp, P)
    assert clock.perf_counter() - t < 3.0
    assert len(s) == 375
