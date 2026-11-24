"""Armed-resumption lifecycle (docs/engines/research-armed.md) and outcomes (spec/03, research §8)."""

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

import pytest

import nifty.engines.research  # noqa: F401
from nifty.contracts import EngineOutput, Instrument
from nifty.engines.context import ConfigError, EngineContext
from nifty.engines.research import baselines as base_mod
from nifty.engines.research.armed import ArmedMachine
from nifty.engines.research.engine import ResearchEngine
from nifty.engines.research.params import ResearchParams
from tests.helpers import CAL, NOW
from tests.unit.engines.research.test_features_baselines import D1, D2, mk

INST = Instrument(instrument_id="csv:T", provider="csv", tradingsymbol="T", tick_size=0.05)


# ---- armed machine -------------------------------------------------------------------------------
class M:
    """Feeds closes to an ArmedMachine, tracking prev close and the bar counter."""

    def __init__(self, **kw: Any) -> None:
        self.m = ArmedMachine(ResearchParams.model_validate(kw))
        self.n, self.prev, self.sign = 0, 100.0, 1

    def bar(self, c: float, h: float | None = None, lo: float | None = None, new_session: bool = False,
            sign: int | None = None) -> tuple[int, list[str], list[dict[str, Any]]]:  # fmt: skip
        self.n += 1
        h = c + 0.2 if h is None else h
        lo = c - 0.2 if lo is None else lo
        b = mk(D1, self.n, c, h, lo, c)
        side, trs = self.m.on_bar(
            b, self.n, self.prev, self.sign if sign is None else sign, new_session
        )
        if sign is not None:
            self.sign = sign
        self.prev = c
        return side, [t.kind for t in trs], [t.payload for t in trs]


def arm_bull(r: M) -> None:
    """Pullback of two lower closes then a resume: arms with trigger 100.2 and invalidation 98.2."""
    r.bar(100.0)
    r.bar(99.0, h=100.2, lo=98.8)  # run 1
    assert r.bar(98.5, h=99.3, lo=98.2)[1] == ["watch"]  # run 2 => watch
    side, kinds, pay = r.bar(99.0)  # first bar closing back with the direction
    assert (side, kinds) == (0, ["armed"])
    assert (pay[0]["trigger"], pay[0]["invalidation"], pay[0]["expiry_bar"], pay[0]["arm"]) == (
        100.2,
        98.2,
        r.n + 5,
        1,
    )


def test_pullback_watch_arm_trigger_then_entry_on_a_completed_close_beyond_the_trigger() -> None:
    r = M()
    arm_bull(r)
    assert r.bar(100.2)[0] == 0  # a close AT the trigger is not beyond it
    side, kinds, _ = r.bar(100.5)
    assert (side, kinds) == (1, [])  # signal known at this close; the engine fills at the next open
    assert r.bar(101.0)[0] == 0 and not r.m.armed  # one entry per setup


def test_the_arming_bar_itself_is_never_evaluated_for_the_trigger() -> None:
    r = M()
    r.bar(100.0)
    r.bar(99.0, h=100.2, lo=98.8)
    r.bar(98.5, h=99.3, lo=98.2)
    side, kinds, _ = r.bar(
        101.0
    )  # resumes ABOVE the trigger 100.2 on the arming bar: arms, no entry
    assert (side, kinds) == (0, ["armed"])
    assert r.bar(101.5)[0] == 1  # evaluated from the next bar on


def test_invalidation_then_exactly_one_rearm_then_locked_until_context_changes() -> None:
    r = M()
    arm_bull(r)
    side, kinds, pay = r.bar(98.0)  # close below the pullback low 98.2
    assert (side, kinds, pay[0]["reason"]) == (0, ["invalidated"], "invalidation")
    r.bar(98.5, h=99.0, lo=98.0)  # new run: closes 98.5 (vs 98.0 resume?) -> start over
    r.bar(97.5, h=98.6, lo=97.3)
    assert r.bar(97.0, h=97.8, lo=96.9)[1] == ["watch"]
    side, kinds, pay = r.bar(97.5)  # second arming (the ONE rearm)
    assert kinds == ["armed"] and pay[0]["arm"] == 2
    assert r.bar(96.0)[1] == ["invalidated"]
    # third attempt: locked
    r.bar(96.2)
    r.bar(95.5)
    r.bar(95.0)
    assert r.bar(95.4)[1] == []
    assert not r.m.armed
    # a flip of the EMA context resets the counter: arming works again (bear context now)
    kinds_seen = [r.bar(95.0, sign=-1)[1]]
    assert kinds_seen == [[]]
    assert r.m.arms_used == 0


def test_expiry_after_five_bars_and_a_trigger_on_the_last_allowed_bar_still_counts() -> None:
    r = M()
    arm_bull(r)  # armed at bar n; may trigger on bars n+1 .. n+5
    for _ in range(4):
        assert r.bar(99.5)[1] == []
    side, kinds, pay = r.bar(99.5)  # n + 5: no trigger => expired
    assert (side, kinds, pay[0]["reason"]) == (0, ["invalidated"], "expired")
    r2 = M()
    arm_bull(r2)
    for _ in range(4):
        r2.bar(99.5)
    assert r2.bar(100.6)[0] == 1  # the last allowed bar triggers before the expiry check


def test_risk_budget_skips_a_setup_wider_than_the_stop_and_never_widens_it() -> None:
    r = M()
    r.bar(100.0)
    r.bar(99.0, h=114.0, lo=98.0)
    r.bar(98.5, h=99.0, lo=97.0)  # run high 114, low 97: trigger - invalidation = 17 > stop 12
    side, kinds, pay = r.bar(99.0)
    assert (side, kinds, pay[0]["reason"]) == (0, ["invalidated"], "risk_budget") and not r.m.armed


def test_session_and_regime_cancel_an_armed_setup_and_unknown_context_does_nothing() -> None:
    r = M()
    arm_bull(r)
    _, kinds, pay = r.bar(99.5, new_session=True)
    assert kinds == ["invalidated"] and pay[0]["reason"] == "session" and not r.m.armed
    r2 = M()
    arm_bull(r2)
    _, kinds2, pay2 = r2.bar(99.5, sign=-1)
    assert kinds2 == ["invalidated"] and pay2[0]["reason"] == "regime_flip"
    r3 = M()
    assert (
        r3.bar(100.0, sign=0)[0] == 0 and r3.bar(99.0, sign=0)[1] == []
    )  # EMAs equal / NaN: no context


def test_pullback_length_limits_and_colour_does_not_matter() -> None:
    r = M(pullback_max=3)
    r.bar(100.0)
    for c in (99.0, 98.0, 97.0, 96.0):  # four lower closes > pullback_max
        r.bar(c)
    assert r.bar(97.0)[1] == []  # the run was discarded: no arming
    g = M()
    g.bar(100.0)
    g.bar(99.0, h=99.3, lo=98.5)
    kinds = g.bar(98.5, h=99.4, lo=98.3)[
        1
    ]  # a green candle (close > open is not tested anywhere) that closes lower
    assert kinds == ["watch"]
    one = M()
    one.bar(100.0)
    one.bar(99.0)  # a single lower close is not enough (pullback_min = 2)
    assert one.bar(99.5)[1] == []


def test_bear_context_mirrors_the_bull_rules() -> None:
    r = M()
    r.sign, r.prev = -1, 100.0
    r.bar(100.0)
    r.bar(101.0, h=101.2, lo=99.8)
    assert r.bar(101.5, h=101.8, lo=101.0)[1] == ["watch"]
    _, kinds, pay = r.bar(101.0)
    assert kinds == ["armed"] and (pay[0]["trigger"], pay[0]["invalidation"]) == (
        99.8,
        101.8,
    )  # trigger = lowest low
    assert r.bar(99.5)[0] == -1  # completed close below the trigger => short


def test_armed_state_roundtrips_through_json() -> None:
    r = M()
    arm_bull(r)
    st = json.loads(json.dumps(r.m.state(), allow_nan=False))
    twin = M()
    twin.m.load(st)
    twin.n, twin.prev = r.n, r.prev
    assert twin.bar(100.5)[0] == r.bar(100.5)[0] == 1


# ---- engine plumbing with a scripted signal (outcomes) -------------------------------------------------
class Rig:
    """Feeds 1m bars to the engine; the baseline is replaced by a scripted signal (close == 777.0)."""

    def __init__(self, mp: pytest.MonkeyPatch, side: int = 1, **kw: Any) -> None:
        mp.setitem(base_mod.BASELINES, "ema_gap_reexpansion", lambda x: side if x.p == 777.0 else 0)
        self.e = ResearchEngine(
            ResearchParams.model_validate({"stop_pts": 12, "target_pts": 10, **kw}),
            EngineContext(INST, "1m", CAL),
        )
        self.i = 0
        self.outs: list[EngineOutput] = []

    def bar(
        self, o: float, h: float, lo: float, c: float, day: date = D1, at: int | None = None
    ) -> EngineOutput:
        self.i = self.i + 1 if at is None else at
        b = mk(day, self.i, o, h, lo, c)
        out = self.e.on_bar(b)
        self.outs.append(out)
        return out

    def signal(self, at: int | None = None) -> None:
        self.bar(100.0, 100.5, 99.5, 777.0, at=at)

    def trades(self) -> list[Any]:
        return [t for o in self.outs for t in o.trades]

    def events(self, kind: str) -> list[dict[str, Any]]:
        return [e.payload for o in self.outs for e in o.events if e.event_type == kind]


MID = 30  # minute 30 of the session = 09:45 IST: inside the entry window


def test_entry_is_the_next_open_with_barriers_anchored_to_the_actual_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = Rig(monkeypatch)
    r.signal(at=MID)  # signal close 777 is irrelevant to the fill
    r.bar(101.0, 105.0, 100.0, 104.0)  # entry at the OPEN 101: stop 89, target 111
    ent = r.events("research.entry")
    assert ent == [
        {**ent[0], "side": "long", "entry_px": 101.0, "stop_px": 89.0, "target_px": 111.0}
    ]
    assert ent[0]["signal_bar_start"] == mk(D1, MID, 1, 1, 1, 1).bar_start_utc.isoformat()


@pytest.mark.parametrize(
    ("bars", "outcome", "exit_px", "flags"),
    [
        ([(101.0, 112.0, 100.0, 111.0)], "TARGET_FIRST", 111.0, []),  # high 112 >= 111, low > 89
        ([(101.0, 102.0, 88.0, 90.0)], "STOP_FIRST", 89.0, []),
        (
            [(101.0, 112.0, 88.0, 100.0)],
            "STOP_FIRST",
            89.0,
            ["ambiguous_bar"],
        ),  # both barriers in one bar
    ],
)
def test_barrier_outcomes_on_the_entry_bar(
    monkeypatch: pytest.MonkeyPatch, bars: Any, outcome: str, exit_px: float, flags: list[str]
) -> None:
    r = Rig(monkeypatch)
    r.signal(at=MID)
    r.bar(*bars[0])
    (t,) = r.trades()
    assert (t.exit_reason, t.exit_px, t.bars_held) == (outcome, exit_px, 1)
    assert t.execution_mode == "conservative" and set(flags) <= set(t.flags)
    assert (
        t.exit_time == mk(D1, MID + 1, 1, 1, 1, 1).bar_start_utc
    )  # the CONTAINING bar's start (exact time unknown)
    (ex,) = r.events("research.exit")
    assert ex["outcome"] == outcome and ex["containing_bar_start"] == t.exit_time.isoformat()


def test_stop_first_is_minus_one_r_with_cost_and_target_pts_20_is_a_separate_experiment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = Rig(monkeypatch, cost_pts=1.0)
    r.signal(at=MID)
    r.bar(101.0, 102.0, 88.0, 90.0)
    (t,) = r.trades()
    assert (t.gross_pts, t.cost_pts, t.net_pts) == (
        -12.0,
        1.0,
        -13.0,
    ) and t.r_multiple == pytest.approx(-13 / 12)
    r2 = Rig(monkeypatch, target_pts=20.0)
    r2.signal(at=MID)
    r2.bar(101.0, 112.0, 100.0, 111.0)  # +10 is NOT the target of the 20-point experiment
    assert r2.trades() == []
    r2.bar(111.0, 121.0, 110.0, 120.0)
    assert r2.trades()[0].exit_reason == "TARGET_FIRST" and r2.trades()[0].exit_px == 121.0


def test_short_side_mirrors_and_a_gap_through_the_stop_fills_at_the_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = Rig(monkeypatch, side=-1)
    r.signal(at=MID)
    r.bar(100.0, 100.5, 99.0, 100.0)  # entry short at 100: stop 112, target 90
    assert (
        r.events("research.entry")[0]["stop_px"] == 112.0
        and r.events("research.entry")[0]["side"] == "short"
    )
    r.bar(
        115.0, 116.0, 114.0, 115.0
    )  # gaps through the stop: conservative fill at the OPEN (worse)
    (t,) = r.trades()
    assert (t.exit_reason, t.exit_px, t.gross_pts) == (
        "STOP_FIRST",
        115.0,
        -15.0,
    ) and "gap_through_stop" in t.flags


def test_time_exit_is_the_actual_directional_return_at_the_close_of_the_tenth_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = Rig(monkeypatch)
    r.signal(at=MID)
    r.bar(100.0, 103.0, 99.0, 101.0)  # bar 1 (entry bar): unrealised +1, peak 1
    r.bar(101.0, 105.0, 100.0, 104.0)  # +4, peak 4
    r.bar(104.0, 104.5, 99.5, 100.5)  # +0.5: drawdown from the peak = 3.5
    for _ in range(6):  # bars 4-9
        r.bar(100.5, 101.0, 99.8, 100.5)
    assert r.trades() == []
    r.bar(100.5, 101.0, 99.8, 100.2)  # bar 10 closes the trade: +0.2
    (t,) = r.trades()
    assert (t.exit_reason, t.bars_held, t.exit_px, t.gross_pts) == (
        "TIME_EXIT",
        10,
        100.2,
        pytest.approx(0.2),
    )
    assert (
        t.exit_time == mk(D1, MID + 10, 1, 1, 1, 1).bar_end_utc
    )  # a time exit has an actual close timestamp
    ex = r.events("research.exit")[0]
    assert ex["time_to_barrier_bars"] is None and ex["bars_held"] == 10
    assert (
        ex["drawdown_pts"] == pytest.approx(3.8) and ex["mfe_pts"] == 5.0 and ex["mae_pts"] == 1.0
    )
    assert ex["first_minute_adverse_pts"] == 1.0  # entry bar low 99 vs entry 100


def test_session_cut_and_data_gap_are_flagged_and_never_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = Rig(monkeypatch, entry_end_hm=1530)
    r.signal(at=373)  # 15:28
    r.bar(100.0, 100.5, 99.5, 100.2)  # minute 374 = 15:29, the last bar of the session
    (t,) = r.trades()
    assert (t.exit_reason, t.bars_held, t.exit_px) == (
        "TIME_EXIT",
        1,
        100.2,
    ) and "session_cut" in t.flags
    g = Rig(monkeypatch)
    g.signal(at=MID)
    g.bar(100.0, 101.0, 99.5, 100.5)
    g.bar(100.5, 101.0, 100.0, 100.8, at=MID + 4)  # minutes 32-33 missing: an interruption
    g.bar(100.8, 111.5, 100.0, 111.0)
    assert "data_gap" in g.trades()[0].flags and g.trades()[0].exit_reason == "TARGET_FIRST"


def test_entry_window_pending_session_and_one_position_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = Rig(monkeypatch)  # window 09:30-14:45 (bar start of the fill bar, inclusive)
    w.signal(at=330)  # 14:45 close => fill bar 14:46 is outside
    w.bar(100.0, 101.0, 99.0, 100.0)
    assert (
        w.events("research.entry") == []
        and w.events("research.invalidated")[0]["reason"] == "window"
    )
    ok = Rig(monkeypatch)
    ok.signal(at=329)  # fill bar 14:45 is inside
    ok.bar(100.0, 101.0, 99.0, 100.0)
    assert len(ok.events("research.entry")) == 1
    ns = Rig(monkeypatch)
    ns.signal(at=374)  # signal on the last bar of the day: the next bar is a new session
    ns.bar(100.0, 101.0, 99.0, 100.0, day=D2, at=0)
    assert (
        ns.events("research.entry") == []
        and ns.events("research.invalidated")[0]["reason"] == "session"
    )
    one = Rig(monkeypatch)
    one.signal(at=MID)
    one.bar(100.0, 103.0, 99.0, 101.0)  # position open
    one.signal()  # a second signal while in the trade is ignored
    assert len(one.events("research.entry")) == 1
    one.bar(100.0, 103.0, 99.0, 101.0)
    assert len(one.events("research.entry")) == 1


def test_duplicate_out_of_order_and_zero_range_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    r = Rig(monkeypatch)
    r.bar(100.0, 101.0, 99.0, 100.0, at=MID)
    n = r.e.n
    again = r.bar(100.0, 101.0, 99.0, 100.0, at=MID)  # exact duplicate
    older = r.bar(100.0, 101.0, 99.0, 100.0, at=MID - 5)  # out of order
    assert again.plots == {} and older.plots == {} and r.e.n == n
    z = r.bar(100.0, 100.0, 100.0, 100.0, at=MID + 1)  # zero range
    assert z.plots["ema_fast"] == z.plots["ema_fast"]  # computed, no exception
    for k in ("d", "e", "m", "anchor_rate", "gap_rate"):
        assert not math.isinf(z.plots[k] or 0.0)


def test_params_validation_and_intrabar_needs_evidence() -> None:
    ctx = EngineContext(INST, "1m", CAL)
    with pytest.raises(ConfigError, match="lower-timeframe"):
        ResearchEngine(ResearchParams.model_validate({"trigger_mode": "intrabar"}), ctx)
    with pytest.raises(ConfigError):
        ResearchEngine(ResearchParams.model_validate({"pullback_min": 4, "pullback_max": 2}), ctx)
    _ = (datetime, timedelta, NOW)
