from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest

from nifty.context.params import ContextParams
from nifty.context.series import DayInputs, OptSeries, build_series, choose_expiry
from nifty.options.bs import bs, years_to_expiry
from nifty.timeutil import IST

DAY = date(2026, 11, 24)
EXP = date(2026, 11, 26)
STRIKES = [25700.0 + 50 * j for j in range(13)]
P = ContextParams()
MINUTES = [datetime(2026, 11, 24, 9, 15, tzinfo=IST).astimezone(UTC) + timedelta(minutes=i)
           for i in range(40)]  # fmt: skip


def call_writing(i: int, k: float) -> float:
    return 1000.0 + 100 * i if i >= 1 else 1000.0


def flat(i: int, k: float) -> float:
    return 1000.0


def make_day(
    *,
    spot: Callable[[int], float] = lambda i: 26000.0,
    ce_iv: float = 18.0,
    pe_iv: float = 18.0,
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
) -> DayInputs:
    """40-minute day from 09:15 IST, VIX 18, options priced from bs() at the given IVs."""
    options = []
    for k in STRIKES:
        for is_call, iv, oi_fn in ((True, ce_iv, ce_oi), (False, pe_iv, pe_oi)):
            close: dict[datetime, float] = {}
            oi: dict[datetime, float] = {}
            for i, m in enumerate(MINUTES):
                g = bs(spot(i), k, years_to_expiry(expiry, m + timedelta(seconds=60)), 0.065,
                       iv / 100.0, is_call)  # fmt: skip
                assert g is not None
                if i == 0:
                    prev_close = 1.5 * g.price
                if alive(i, k, is_call):
                    close[m] = g.price
                    if oi_alive(i, k, is_call):
                        oi[m] = oi_fn(i, k)
            options.append(OptSeries(k, is_call, expiry, close, oi, prev_close, prev_oi))
    return DayInputs(
        day=day,
        minutes=list(MINUTES),
        spot={m: spot(i) for i, m in enumerate(MINUTES)},
        prev_spot_close=25950.0,
        vix={m: vix(i) for i, m in enumerate(MINUTES)},
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
    assert expiry == EXP and notes == []
    assert s[idx(9, 16)]["candidate"] == "BEARISH"
    assert s[idx(9, 31)]["bias"] == "NONE"
    first = idx(9, 32)
    assert s[first]["bias"] == "BEARISH"
    assert s[first]["bias_since"] == int(MINUTES[first].timestamp())
    assert all(x["bias"] == "BEARISH" and x["bias_since"] == s[first]["t"] for x in s[first:])
    x = s[first]
    assert x["pe"]["iv"] == pytest.approx(18.0, abs=0.05)
    assert x["ce"]["iv"] == pytest.approx(18.0, abs=0.05)
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
    _, s, _ = build_series(make_day(pe_iv=21.0), P)
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
    legs = [bs(26030.0, 26050.0, t, 0.065, 0.18, c) for c in (True, False)]
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

    _, s, _ = build_series(make_day(pe_oi=pe_writing, alive=alive), P)
    assert s[10]["w_day"] == pytest.approx((50 - 700) / 750)
    # PE 25900 last bar at i=19 is 120 s old at i=21: still carried
    assert s[21]["w_day"] == pytest.approx((50 * 19 - 700 * 21) / (50 * 19 + 700 * 21))
    assert s[22]["w_day"] == -1.0  # PE 25900 dropped
    assert s[31]["na_reason"] is None and s[31]["bias"] == "BEARISH"
    assert s[32]["na_reason"] == "no option data" and s[32]["w_day"] is None
    assert s[32]["bias"] == "BEARISH" and s[33]["bias"] == "NONE"
    assert all(x["candidate"] == "NONE" for x in s[32:])


def test_baseline_fallback_first_tick() -> None:
    _, s, notes = build_series(make_day(prev_oi=None), P)
    assert "writing since first tick" in notes
    assert s[idx(9, 32)]["bias"] == "BEARISH"


def test_expiry_day_uses_next_weekly() -> None:
    expiry, s, notes = build_series(make_day(day=DAY, expiries=(DAY, EXP)), P)
    assert expiry == EXP and "expiry day: next weekly" in notes
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
    _, s, _ = build_series(make_day(ce_iv=20.0), P)
    assert s[20]["ce"]["note"] == "IV rich vs own 5-day"  # 20 > 17.5 + 1.8
    assert s[20]["rv"] == 12.0 and s[20]["pe"]["note"] is None


def test_shown_bias_holds_above_w_exit() -> None:
    k = idx(9, 40)

    def ce(i: int, strike: float) -> float:
        return 1000.0 + 100 * min(i, k) if i >= 1 else 1000.0

    def pe(i: int, strike: float) -> float:
        return 2400.0 if i >= k else 1000.0

    _, s, _ = build_series(make_day(ce_oi=ce, pe_oi=pe), P)
    assert s[k]["w_day"] == pytest.approx((1400 - 2500) / 3900)  # below w_min, above w_exit
    assert s[k]["one_sided"] == 0 and s[k]["candidate"] == "BEARISH"
    assert s[k + 1]["bias"] == "BEARISH"
    assert s[k + 2]["candidate"] == "NONE" and s[k + 2]["bias"] == "BEARISH"  # w_roll turned +
    assert s[k + 3]["bias"] == "NONE"
