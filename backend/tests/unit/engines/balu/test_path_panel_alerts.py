"""Steps 13-15 from the Pine rules (L770-895): path-history episodes and statistics, the 13-row
panel, regime-flip and divergence alerts."""

import json
from typing import Any

import pytest

from nifty.engines.balu.panel import r_half_up, rows
from nifty.engines.balu.path import PathHistory, state_id
from tests.unit.engines.balu.helpers import D1, D2, D3, OHLC, Harness

NOHTF: dict[str, Any] = {"use_htf_levels": False}


class Run:
    """Drives PathHistory bar by bar with a real barrier pair (95 / 105) unless overridden."""

    def __init__(self, horizon: int = 3) -> None:
        self.ph, self.n, self.horizon = PathHistory(), 0, horizon

    def bar(
        self, sid: int, high: float = 101.0, low: float = 99.0, close: float = 100.0, **kw: Any
    ) -> None:
        self.n += 1
        args: dict[str, Any] = dict(
            in_session=True, new_session=False, session_ends=False, next_up=105.0, next_dn=95.0,
            up_proj=False, dn_proj=False, day="d1",
        )  # fmt: skip
        args.update(kw)
        self.ph.on_bar(
            sid=sid, high=high, low=low, close=close, bar_index=self.n, horizon=self.horizon, **args
        )


def test_state_id_has_27_buckets() -> None:
    assert state_id(0, -1, 0) == 0 and state_id(2, 1, 2) == 26 and state_id(1, 0, 1) == 13
    assert (
        len({state_id(r, f, loc) for r in range(3) for f in (-1, 0, 1) for loc in range(3)}) == 27
    )


def test_episode_opens_only_on_a_confirmed_state_change_with_real_barriers_and_is_never_queued() -> (
    None
):
    r = Run()
    r.bar(4)  # first observation: prevState was NaN, so nothing "changed"
    assert r.ph.p_state is None
    r.bar(5, high=200.0)  # change 4 -> 5, 95 < close 100 < 105, both real: episode opens
    assert r.ph.p_state == 5 and (r.ph.p_up, r.ph.p_dn, r.ph.p_bar) == (105.0, 95.0, 2)
    assert sum(r.ph.hit_up) == 0  # the start bar itself (high 200) is never evaluated
    r.bar(6)  # a transition while busy is skipped, never queued
    assert r.ph.p_state == 5
    r.bar(6, high=106.0)  # resolves up; 6 -> 6 is no change, so resolution alone starts nothing
    assert r.ph.hit_up[5] == 1 and r.ph.p_state is None
    r.bar(6)
    assert r.ph.p_state is None  # state unchanged since: nothing queued from earlier skips


@pytest.mark.parametrize(
    "kw",
    [
        dict(up_proj=True),
        dict(dn_proj=True),
        dict(next_up=float("nan")),
        dict(next_dn=float("nan")),
        dict(next_up=99.0),  # close is not below the upper barrier
        dict(next_dn=101.0),
        dict(session_ends=True),
        dict(in_session=False),
    ],
)
def test_no_episode_without_real_barriers_or_on_the_last_bar_of_the_session(
    kw: dict[str, Any],
) -> None:
    r = Run()
    r.bar(4)
    r.bar(5, **kw)
    assert r.ph.p_state is None


def test_first_bar_of_a_session_resets_prev_state_so_no_episode_starts_there() -> None:
    r = Run()
    r.bar(4)
    r.bar(5, new_session=True)  # prevState := NaN before the change check
    assert r.ph.p_state is None and r.ph.prev_state == 5
    r.bar(6)  # now 5 -> 6 is a change
    assert r.ph.p_state == 6


@pytest.mark.parametrize(
    ("high", "low", "field"),
    [(105.0, 99.0, "hit_up"), (101.0, 95.0, "hit_dn"), (106.0, 94.0, "both_hit")],
)
def test_resolution_up_down_or_both_in_the_same_bar(high: float, low: float, field: str) -> None:
    r = Run()
    r.bar(4)
    r.bar(5)
    r.bar(5, high=high, low=low)
    assert getattr(r.ph, field)[5] == 1 and r.ph.p_state is None


def test_a_hit_on_bar_h_beats_the_timeout_and_timeout_needs_h_bars() -> None:
    r = Run(horizon=3)  # start at bar 2: bars 3 and 4 stay open, bar 5 is bar_index - pBar = 3
    r.bar(4)
    r.bar(5)
    r.bar(5)
    r.bar(5)
    assert r.ph.p_state == 5 and r.ph.timed_out[5] == 0  # 4 - 2 = 2 < 3
    r.bar(5, high=105.0)  # bar H itself: the hit wins over the timeout
    assert r.ph.hit_up[5] == 1 and r.ph.timed_out[5] == 0
    r2 = Run(horizon=3)
    for sid in (4, 5, 5, 5, 5):
        r2.bar(sid)  # no hit by bar H: timeout
    assert r2.ph.timed_out[5] == 1 and r2.ph.p_state is None


def test_session_boundaries_censor_an_unfinished_episode() -> None:
    r = Run()
    r.bar(4)
    r.bar(5)
    r.bar(
        5, new_session=True, high=106.0
    )  # a new session never resolves with tomorrow's gap: it is cut
    assert r.ph.session_cut[5] == 1 and r.ph.hit_up[5] == 0 and r.ph.p_state is None
    r2 = Run()
    r2.bar(4)
    r2.bar(5)
    r2.bar(5, session_ends=True)  # no hit, no timeout, last bar of the session: cut
    assert r2.ph.session_cut[5] == 1
    r3 = Run()
    r3.bar(4)
    r3.bar(5)
    r3.bar(5, in_session=False)  # out of session counts as a boundary
    assert r3.ph.session_cut[5] == 1 and r3.ph.prev_state is None


def test_sample_days_increments_once_per_bucket_per_day() -> None:
    r = Run(horizon=1)
    for sid in (
        4,
        5,
        4,
        5,
    ):  # bucket 5 entered twice on d1 (each episode times out at the next bar)
        r.bar(sid)
        r.bar(sid)
    assert r.ph.sample_days[5] == 1 and r.ph.last_sample_day[5] == "d1"
    r.bar(4, new_session=True, day="d2")
    r.bar(5, day="d2")  # the same bucket on a new day: counted again
    assert r.ph.sample_days[5] == 2 and r.ph.sample_days[4] == 1  # bucket 4 was sampled once on d1


def test_statistics_arithmetic_and_pending() -> None:
    ph = PathHistory()
    s = 7
    ph.hit_up[s], ph.hit_dn[s], ph.timed_out[s], ph.both_hit[s], ph.session_cut[s] = 6, 2, 1, 2, 3
    ph.sample_days[s] = 4
    ph.p_state = s
    st = ph.stats(s, True, 14)
    assert (st.n_resolved, st.n_finished, st.n_pending, st.sample_days) == (8, 14, 1, 4)
    assert st.resolved_share == 75.0
    assert st.history_lo == pytest.approx(100 * 6 / 14) and st.history_hi == pytest.approx(
        100 * 11 / 14
    )
    assert st.prob_ready is True and ph.stats(s, True, 15).prob_ready is False
    assert ph.stats(s, False, 1).prob_ready is False  # useProb off
    assert ph.stats(s + 1, True, 1).n_pending == 0  # the episode belongs to another bucket
    empty = ph.stats(20, True, 1)
    assert empty.resolved_share is None and empty.history_lo is None and empty.n_finished == 0


def test_path_state_roundtrips_through_json() -> None:
    r = Run()
    for sid in (4, 5):
        r.bar(sid)
    st = json.loads(json.dumps(r.ph.state(), allow_nan=False))
    q = PathHistory()
    q.load(st)
    assert q.state() == r.ph.state() and q.p_state == 5 and q.p_up == 105.0


# ---- panel -------------------------------------------------------------------------------------------
def raw(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        regime_idx=2, flow_state=1, loc_idx=0, use_real_vol=False, close=100.0, next_up=105.04,
        next_dn=None, next_up_proj=True, next_dn_proj=False, use_prob=True, prob_min_n=5, prob_horizon=20,
        stats=dict(n_up=6, n_dn=2, n_timeout=1, n_both=2, n_cut=3, n_pending=1, sample_days=3,
                   n_resolved=8, n_finished=14, resolved_share=75.0, history_lo=100 * 6 / 14,
                   history_hi=100 * 11 / 14, prob_ready=True),
        bear_div=False, bull_div=True, fp_valid=True, press_buy=True, press_sell=False, gold_anchor="VWAP",
    )  # fmt: skip
    base.update(over)
    return base


def test_panel_has_13_rows_in_pine_order_with_pine_strings() -> None:
    got = rows(raw())
    assert [r["label"] for r in got] == [
        "Regime", "Flow (range proxy)", "Location", "To Supply", "To Demand", "History (closed state)",
        "Up / Dn / Timeout / Both / Cut", "Up first | resolved only", "Up by H | history bounds",
        "Forecast / edge / effective n", "Divergence", "Pressure | Gold", "Sampling",
    ]  # fmt: skip
    v = [r["value"] for r in got]
    assert v == [
        "BULL", "RISING", "AT DEMAND", "5.0 (proj)", "—", "14 done / 1 open / 3 days", "6 / 2 / 1 / 2 / 3",
        "75% (n=8)", "43..79% (not a CI)", "Not established", "BULLISH", "BUY | VWAP",
        "Transitions; real zones; H=20",
    ]  # fmt: skip
    assert [r["role"] for r in got][:5] == ["bull", "bull", "demand", "supply", "demand"]
    assert got[10]["role"] == "bull" and got[11]["role"] == "demand"


def test_panel_strings_for_thin_samples_off_and_unavailable_pressure() -> None:
    thin = rows(raw(prob_min_n=10))  # 8 resolved < 10, 14 finished >= 10
    assert (
        thin[7]["value"] == "Too few resolved episodes" and thin[8]["value"] == "43..79% (not a CI)"
    )
    few = rows(raw(prob_min_n=20))
    assert few[8]["value"] == "Too few finished episodes"
    off = rows(raw(use_prob=False))
    assert [off[i]["value"] for i in (5, 6, 7, 8)] == ["OFF", "—", "OFF", "OFF"]
    na = rows(
        raw(
            fp_valid=False,
            press_buy=False,
            use_real_vol=True,
            loc_idx=2,
            regime_idx=0,
            flow_state=-1,
        )
    )
    assert (
        na[11]["value"] == "n/a (LTF unavailable/invalid) | VWAP"
        and na[1]["label"] == "Flow (volume proxy)"
    )
    assert (na[0]["value"], na[1]["value"], na[2]["value"]) == ("BEAR", "FALLING", "AT SUPPLY")
    assert (
        rows(raw(press_buy=False, press_sell=True, provisional=True))[11]["value"] == "SELL? | VWAP"
    )
    assert rows(raw(press_buy=False, bull_div=False))[11]["value"] == "— | VWAP"
    assert (
        rows(raw(next_dn=96.26, next_up=None))[4]["value"] == "3.7"
        and rows(raw(next_up=None))[3]["value"] == "—"
    )


def test_round_half_up_not_bankers_rounding() -> None:
    assert r_half_up(2.5) == 3.0 and r_half_up(0.5) == 1.0 and r_half_up(0.05, 1) == 0.1
    assert r_half_up(75.0) == 75.0


def test_engine_panel_is_the_latest_bar_and_survives_a_restore() -> None:
    h = Harness(**NOHTF)
    assert h.engine.panel() is None
    h.day(D1, [(100, 101, 99, 100)] * 20)
    p = h.engine.panel()
    assert p is not None and len(p["rows"]) == 13 and p["rows"][0]["value"] == "NEUTRAL"
    snap = json.loads(json.dumps(h.engine.snapshot(), allow_nan=False))
    twin = Harness(**NOHTF)
    twin.engine.restore(snap)
    assert twin.engine.panel() == p


# ---- alerts ------------------------------------------------------------------------------------------
def around(c: float) -> OHLC:
    return (c, c + 1, c - 1, c)


def alerts(h: Harness) -> list[tuple[int, str]]:
    return [
        (i, e.payload["kind"])
        for i, o in enumerate(h.outs)
        for e in o.events
        if e.event_type == "alert"
    ]


def test_regime_flip_alerts_fire_on_the_flip_and_repeat_each_session() -> None:
    h = Harness(gold_source="Daily Pivot (PP)", **NOHTF)
    h.day(D1, [(100, 101, 99, 100)] * 20)  # PP = 100; ATR = 2 => deadband 0.5
    h.day(D2, [around(c) for c in (100.6, 100.2, 99.6, 99.4, 100.0)])  # regime 2 2 2 0 0
    h.day(D3, [around(100.2), around(100.6)])  # the state resets each session: 1 then 2 again
    assert h.plot("regime_idx")[20:] == [2.0, 2.0, 2.0, 0.0, 0.0, 1.0, 2.0]
    # no flip on the first bar; BULL at the first 2, BEAR at the first 0, BULL again after the reset
    assert alerts(h) == [(20, "regime_bull"), (23, "regime_bear"), (26, "regime_bull")]


def test_a_regime_that_survives_the_session_boundary_does_not_alert_twice() -> None:
    h = Harness(gold_source="Daily Pivot (PP)", **NOHTF)
    h.day(D1, [(100, 101, 99, 100)] * 20)  # PP = 100, ATR 2, deadband 0.5
    h.day(D2, [around(100.6), around(100.0)])  # state 1 kept inside the band: regime 2 both bars
    # day 3: PP = (101.6 + 99 + 100) / 3 = 100.2; the state resets to 0, then 100.8 > 100.7 flips it
    # back to 1 on the same bar: regime 2 again, and regimeIdx[1] was already 2
    h.day(D3, [around(100.8)])
    assert h.plot("regime_idx")[20:] == [2.0, 2.0, 2.0]
    assert alerts(h) == [(20, "regime_bull")]


def test_divergence_alerts_come_with_the_divergence_event_on_the_confirming_bar() -> None:
    from tests.unit.engines.balu.test_moving_line import D_1, H1, pattern

    h = Harness(div_pivot_len=2, **NOHTF)
    h.day(D1, pattern(H1, D_1))
    kinds = [
        (i, e.event_type, e.payload.get("kind") or e.payload.get("side"))
        for i, o in enumerate(h.outs)
        for e in o.events
    ]
    assert (9, "divergence", "bear") in kinds and (9, "alert", "divergence_bear") in kinds
    names = [
        e.payload["name"]
        for o in h.outs
        for e in o.events
        if e.payload.get("kind") == "divergence_bear"
    ]
    assert names == ["Bearish Divergence"]


def test_use_prob_off_leaves_the_history_untouched() -> None:
    h = Harness(use_prob=False, **NOHTF)
    h.day(D1, [(100, 101, 99, 100)] * 30)
    assert (
        set(h.plot("n_up")) == {0.0} and h.engine.slots["path"].state()["sample_days"] == [0] * 27
    )
    assert h.engine.panel()["rows"][5]["value"] == "OFF"  # type: ignore[index]
