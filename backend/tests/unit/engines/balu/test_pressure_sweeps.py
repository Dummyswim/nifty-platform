"""Key-level rails (L577-625), intrabar pressure (L664-700), sweep machines (L696-755) and the
provisional guarantee, from the Pine rules on hand-built bars."""

import json
import math
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from nifty.contracts import Bar, EngineOutput
from nifty.engines.balu.location import Location
from nifty.engines.balu.pressure import Reading
from nifty.engines.balu.steps import BarFrame
from nifty.engines.balu.sweeps import Sweeps, far_from_all, sweeps
from nifty.engines.context import ConfigError
from tests.helpers import CAL
from tests.unit.engines.balu.helpers import D1, D2, D3, OHLC, Harness, bar1

NOHTF: dict[str, Any] = {"use_htf_levels": False}
FLAT: OHLC = (100, 101, 99, 100)


def rails(h: Harness, lo: int, hi: int) -> list[tuple[str, int, bool, float | None, Any]]:
    return [
        (e.id, e.ver, e.deleted, e.p0, e.style.get("dash"))
        for o in h.outs[lo:hi]
        for e in o.overlay_ops
        if e.id.startswith("kl:")
    ]


# ---- key levels --------------------------------------------------------------------------------
def test_rails_are_rebuilt_each_session_and_the_old_ones_are_deleted_first() -> None:
    h = Harness(**NOHTF)
    h.day(D1, [FLAT] * 20)
    h.day(D2, [FLAT] * 3)
    h.day(D3, [FLAT])
    d1 = rails(h, 0, 20)
    assert d1 == [
        ("kl:ORH:2026-11-02", 0, False, 101.0, "dashed"),
        ("kl:ORL:2026-11-02", 0, False, 99.0, "dashed"),
    ]
    assert [r[0] for r in d1] and h.outs[
        2
    ].overlay_ops  # created on the bar where dayLen == orBars == 3
    d2 = rails(h, 20, 23)
    assert d2 == [
        ("kl:ORH:2026-11-02", 1, True, 101.0, None), ("kl:ORL:2026-11-02", 1, True, 99.0, None),  # clear first
        ("kl:PDH:2026-11-03", 0, False, 101.0, "solid"), ("kl:PDL:2026-11-03", 0, False, 99.0, "solid"),
        ("kl:PDC:2026-11-03", 0, False, 100.0, "dotted"),
        ("kl:ORH:2026-11-03", 0, False, 101.0, "dashed"), ("kl:ORL:2026-11-03", 0, False, 99.0, "dashed"),
    ]  # fmt: skip
    d3 = rails(h, 23, 24)
    assert {(r[0], r[2]) for r in d3 if r[2]} == {
        ("kl:PDH:2026-11-03", True), ("kl:PDL:2026-11-03", True), ("kl:PDC:2026-11-03", True),
        ("kl:ORH:2026-11-03", True), ("kl:ORL:2026-11-03", True),
    }  # fmt: skip


def test_or_rail_created_after_the_clear_when_orbars_is_one_and_pivot_rails_are_optional() -> None:
    h = Harness(or_minutes=5, kl_pivot=True, **NOHTF)  # orBars = 1: same bar as the clear, after it
    h.day(D1, [FLAT] * 15)
    h.day(D2, [FLAT])
    ids = [(r[0], r[2]) for r in rails(h, 15, 16)]
    # pp = (101 + 99 + 100) / 3 = 100, r1 = 2*100 - 99 = 101, s1 = 2*100 - 101 = 99
    assert ids == [("kl:ORH:2026-11-02", True), ("kl:ORL:2026-11-02", True),
                   ("kl:PDH:2026-11-03", False), ("kl:PDL:2026-11-03", False), ("kl:PDC:2026-11-03", False),
                   ("kl:PP:2026-11-03", False), ("kl:R1:2026-11-03", False), ("kl:S1:2026-11-03", False),
                   ("kl:ORH:2026-11-03", False), ("kl:ORL:2026-11-03", False)]  # fmt: skip
    assert [r[3] for r in rails(h, 15, 16) if "PP" in r[0] or "R1" in r[0] or "S1" in r[0]] == [
        100.0,
        101.0,
        99.0,
    ]
    assert Harness(show_key_levels=False, **NOHTF).day(D1, [FLAT] * 4) and True
    off = Harness(show_key_levels=False, **NOHTF)
    off.day(D1, [FLAT] * 4)
    assert rails(off, 0, 4) == []


def test_no_prior_day_rails_on_the_first_session() -> None:
    h = Harness(**NOHTF)
    h.day(D1, [FLAT])
    assert rails(h, 0, 1) == []  # pdH/pdL/pdC are NaN and skipped


# ---- pressure ----------------------------------------------------------------------------------
def sub(c_at: str, rng: float = 1.0) -> OHLC:
    """A 1m sub-bar of the given range whose close is at its high ('hi'), low ('lo') or middle."""
    lo = 100.0
    return (lo, lo + rng, lo, {"hi": lo + rng, "lo": lo, "mid": lo + rng / 2}[c_at])


def pbars(h: Harness, specs: list[list[OHLC]], **kw: Any) -> list[EngineOutput]:
    chart = [FLAT] * len(specs)
    return h.day(D1, chart, specs)


def test_buy_and_sell_pressure_arithmetic_and_outputs() -> None:
    h = Harness(fp_at_zone_only=False, **NOHTF)
    pbars(h, [[sub("hi")] * 5, [sub("lo")] * 5])
    # each sub-bar: range 1, effort 1 (no volume), signed = (2c - h - l) / (h - l) * 1 = +1 / -1
    assert h.plot("fp_n")[:2] == [5.0, 5.0] and h.plot("fp_tot")[:2] == [5.0, 5.0]
    assert h.plot("fp_imb")[:2] == [1.0, -1.0] and h.plot("fp_valid")[:2] == [1.0, 1.0]
    assert h.plot("press_buy")[:2] == [1.0, 0.0] and h.plot("press_sell")[:2] == [0.0, 1.0]
    ev = [
        (e.event_type, e.payload["kind"], e.payload["imb"])
        for o in h.outs
        for e in o.events
        if e.event_type == "alert"
    ]
    assert ev == [("alert", "press_buy", 1.0), ("alert", "press_sell", -1.0)]
    marks = [
        (e.id[:2], e.p0, e.style["pos"], e.style["shape"])
        for o in h.outs
        for e in o.overlay_ops
        if e.id[:2] in ("pb", "ps")
    ]
    assert marks == [
        ("pb", 99.0, "below", "circle"),
        ("ps", 101.0, "above", "circle"),
    ]  # circle below / above


def test_pressure_is_suppressed_without_enough_sub_bars_or_below_the_threshold() -> None:
    h = Harness(fp_at_zone_only=False, **NOHTF)
    pbars(
        h,
        [
            [sub("hi")] * 2,
            [sub("hi"), sub("hi"), sub("hi"), sub("lo"), sub("lo")],
            [sub("mid")] * 5,
        ],
    )
    assert h.plot("fp_n")[:3] == [2.0, 5.0, 5.0]
    assert h.plot("fp_valid")[0] == 0.0 and h.plot("press_buy")[0] == 0.0  # 2 < fpMinSubBars (3)
    assert (
        h.plot("fp_imb")[1] == pytest.approx(0.2) and h.plot("press_buy")[1] == 0.0
    )  # 0.2 < fpImbal 0.5
    assert h.plot("fp_imb")[2] == 0.0  # close at the middle of every sub-bar: nothing one-sided
    z = Harness(fp_at_zone_only=False, **NOHTF)
    z.day(D1, [FLAT], [[(100, 100, 100, 100)] * 5])  # every sub-bar has zero range: effort 0
    assert z.plot("fp_valid") == [0.0] and z.plot("fp_imb") == [0.0]  # fpTot > 0 is required


def test_flat_resolution_equal_to_the_chart_is_suppressed_and_a_bad_divisor_is_an_error() -> None:
    h = Harness(fp_ltf="5", fp_at_zone_only=False, **NOHTF)
    h.day(D1, [FLAT])
    assert h.plot("fp_n") == [0.0] and h.plot("fp_valid") == [
        0.0
    ]  # fpLtf == chart: nothing to look inside
    with pytest.raises(ConfigError, match="does not divide"):
        Harness(fp_ltf="3", **NOHTF).day(D1, [FLAT])
    with pytest.raises(ConfigError):
        Harness(fp_ltf="7", **NOHTF).day(D1, [FLAT])
    off = Harness(show_footprint=False, fp_at_zone_only=False, **NOHTF)
    pbars(off, [[sub("hi")] * 5])
    assert off.plot("fp_valid") == [0.0] and off.plot("press_buy") == [0.0]


def test_effort_average_is_nan_until_full_then_requires_a_big_bar() -> None:
    h = Harness(fp_at_zone_only=False, fp_eff_len=5, **NOHTF)
    big = [sub("hi", 2.0)] * 5  # effort 2 per sub-bar: tot 10, net 10
    pbars(h, [[sub("hi")] * 5] * 6 + [big])
    # bars 1-4: fpAvg is NaN => big whenever valid. bar 5: avg = 5 (window full); 5 >= 5 * 1.3 is false.
    # bar 6 also false. bar 7: window 5,5,5,5,10 => avg 6; 10 >= 7.8
    assert h.plot("press_buy") == [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0]


def test_pressure_only_counts_at_a_zone_when_fp_at_zone_only() -> None:
    h = Harness(**NOHTF)  # fp_at_zone_only defaults to True and no zone exists
    pbars(h, [[sub("hi")] * 5])
    assert h.plot("fp_valid") == [1.0] and h.plot("press_buy") == [0.0]


# ---- sweeps ------------------------------------------------------------------------------------
class Rig:
    """Drives the sweeps step with a hand-made location (zone centre 101, bot 100 / supply 109, top 110)."""

    def __init__(self, **kw: Any) -> None:
        from nifty.engines.balu.params import BaluParams

        self.sw = Sweeps()
        self.n = 0
        self.eng = SimpleNamespace(
            p=BaluParams.model_validate(kw), ctx=SimpleNamespace(mintick=0.05),
            slots={"sweeps": self.sw, "core": SimpleNamespace(s=SimpleNamespace(n_bars=0))},
        )  # fmt: skip

    def bar(self, o: float, h: float, lo: float, c: float, tap: tuple[float, float] | None = None,
            sup: tuple[float, float] | None = None, new_session: bool = False) -> BarFrame:  # fmt: skip
        self.n += 1
        self.eng.slots["core"].s.n_bars = self.n
        start = CAL.session_bounds(D1)[0] + timedelta(minutes=5 * self.n)
        f = BarFrame(
            bar=bar1(start, o, h, lo, c, "5m", 5),
            out=EngineOutput(),
            atr=2.0,
            new_session=new_session,
        )
        loc = Location()
        if tap:
            loc.tap_demand_bot, loc.tap_demand_c = tap
        if sup:
            loc.tap_supply_top, loc.tap_supply_c = sup
        f.extra["location"], f.extra["fp"] = loc, Reading(imb=0.4)
        sweeps(self.eng, f)  # type: ignore[arg-type]
        return f


DEM = (100.0, 101.0)  # (zone bot, zone centre)
SUP = (110.0, 109.0)  # (zone top, zone centre)


def conf(f: BarFrame) -> tuple[float, float]:
    return f.out.plots["sweep_d_conf"], f.out.plots["sweep_s_conf"]  # type: ignore[return-value]


def test_demand_sweep_arms_then_confirms_on_a_close_above_the_sweep_bar_high() -> None:
    r = Rig()
    f = r.bar(
        100.4, 101.0, 99.5, 100.6, tap=DEM
    )  # low < bot, close > bot, lower wick 0.9/1.5 >= 0.2
    assert (
        conf(f) == (0.0, 0.0) and f.out.events == [] and r.sw.d.bar == 1
    )  # armed; the sweep bar itself never confirms
    assert r.sw.d.x == 101.0 and r.sw.d.edge == 100.0 and r.sw.d.c == 101.0
    assert conf(r.bar(100.6, 100.9, 100.3, 100.8)) == (0.0, 0.0)  # inside the window, not beyond X
    f3 = r.bar(100.8, 101.8, 100.7, 101.5)  # close 101.5 > X = 101: confirmed, on THIS bar
    assert conf(f3) == (1.0, 0.0) and r.sw.d.done == [101.0] and r.sw.d.bar is None
    ev = [(e.payload["kind"], e.payload["zone_center"], e.payload["imb"]) for e in f3.out.events]
    assert ev == [("sweep_demand", 101.0, 0.4)]
    assert [(m.id[:3], m.p0, m.style["shape"]) for m in f3.out.overlay_ops] == [
        ("swd", 100.7, "xcross")
    ]


def test_pending_sweep_is_cancelled_by_a_close_through_the_zone_or_by_timeout_and_may_rearm_at_once() -> (
    None
):
    r = Rig()
    r.bar(100.4, 101.0, 99.5, 100.6, tap=DEM)
    f = r.bar(100.5, 100.7, 99.5, 99.8)  # close < bot: cancel (no confirm)
    assert conf(f) == (0.0, 0.0) and r.sw.d.bar is None and r.sw.d.done == []
    r.bar(100.4, 101.0, 99.5, 100.6, tap=DEM)  # armed at n = 3
    for _ in range(3):  # bars +1..+3 stay inside (bot, X]
        r.bar(100.5, 100.9, 100.3, 100.7)
    assert r.sw.d.bar == 3
    f6 = r.bar(
        100.4, 101.0, 99.5, 100.6, tap=DEM
    )  # n = 7: 7 - 3 = 4 > 3: cancel, then re-arm on the same bar
    assert conf(f6) == (0.0, 0.0) and r.sw.d.bar == 7


def test_done_list_blocks_a_second_confirmation_of_the_same_zone_within_0_7_atr_until_a_new_session() -> (
    None
):
    r = Rig()
    r.bar(100.4, 101.0, 99.5, 100.6, tap=DEM)
    r.bar(100.8, 101.8, 100.7, 101.5)
    assert r.sw.d.done == [101.0]
    r.bar(
        100.4, 101.0, 99.5, 100.6, tap=(100.5, 101.5)
    )  # centre 101.5: |101.5 - 101| = 0.5 <= 0.7 * 2 = 1.4
    assert r.sw.d.bar is None  # not far from a done centre: never armed
    r.bar(102.4, 103.0, 101.5, 102.6, tap=(102.0, 103.0))  # centre 103: 2.0 > 1.4 => armed
    assert r.sw.d.bar is not None
    r.bar(100.0, 100.5, 99.9, 100.2, new_session=True)  # new session clears pending and done
    assert r.sw.d.bar is None and r.sw.d.done == []
    r.bar(100.4, 101.0, 99.5, 100.6, tap=DEM)
    assert r.sw.d.bar is not None  # the same zone can confirm again the next day


def test_supply_sweep_mirrors_with_high_low_swapped() -> None:
    r = Rig()
    f = r.bar(
        109.6, 110.5, 109.2, 109.4, sup=SUP
    )  # high > top, close < top, upper wick (110.5 - 109.6) / 1.3 >= 0.2
    assert r.sw.s.bar == 1 and r.sw.s.x == 109.2 and conf(f) == (0.0, 0.0)  # X is the sweep bar LOW
    f2 = r.bar(109.3, 109.5, 108.6, 108.9)  # close < X
    assert conf(f2) == (0.0, 1.0) and r.sw.s.done == [109.0]
    assert [e.payload["kind"] for e in f2.out.events] == ["sweep_supply"]
    assert [(m.id[:3], m.p0, m.style["pos"]) for m in f2.out.overlay_ops] == [
        ("sws", 109.5, "above")
    ]
    r2 = Rig()
    r2.bar(109.6, 110.5, 109.2, 109.4, sup=SUP)
    assert (
        conf(r2.bar(109.4, 110.4, 109.3, 110.2)) == (0.0, 0.0) and r2.sw.s.bar is None
    )  # close > top: cancelled


def test_a_wick_below_the_minimum_is_not_a_sweep_and_raw_markers_need_conf_only_off() -> None:
    r = Rig()
    r.bar(
        100.9, 101.0, 99.95, 101.0, tap=DEM
    )  # lower wick (100.9 - 99.95) / 1.05 > 0.2 -> armed, sanity
    assert r.sw.d.bar == 1
    thin = Rig()
    thin.bar(100.0, 101.5, 99.9, 100.2, tap=DEM)  # wick 0.1 / 1.6 = 0.0625 < 0.2: no sweep
    assert thin.sw.d.bar is None
    raw = Rig(sweep_conf_only=False)
    f = raw.bar(
        100.4, 101.0, 99.5, 100.6, tap=DEM
    )  # v2.1 mode: the mark sits on the sweep bar itself
    assert [e.payload["kind"] for e in f.out.events] == ["sweep_demand"] and conf(f) == (0.0, 0.0)
    off = Rig(show_footprint=False)
    off.bar(100.4, 101.0, 99.5, 100.6, tap=DEM)
    g = off.bar(100.8, 101.8, 100.7, 101.5)
    assert (
        conf(g) == (1.0, 0.0) and g.out.events == [] and g.out.overlay_ops == []
    )  # machine runs, marks do not
    assert far_from_all([101.0], 103.0, 1.4) and not far_from_all([101.0], 102.3, 1.4)


# ---- provisional ---------------------------------------------------------------------------------
def test_on_provisional_emits_early_pressure_and_never_touches_state() -> None:
    h = Harness(fp_at_zone_only=False, **NOHTF)
    h.day(D1, [FLAT] * 20)  # atr valid, zones built
    before = json.dumps(h.engine.snapshot(), sort_keys=True, allow_nan=False)
    start = h.starts[-1] + timedelta(minutes=5)
    # history bars have effort 4 (ranges 0 + 1 + 2 + 0 + 1), so the average is ~3.95 and a "big" bar needs
    # >= 1.3x that: three one-sided sub-bars of range 3 give effort 9
    for k in range(3):
        h.ctx.append_1m(bar1(start + timedelta(minutes=k), 100.0, 103.0, 100.0, 103.0, "1m", 1))
    forming = Bar(
        instrument_id="csv:T", provider="csv", timeframe="5m", bar_start_utc=start,
        bar_end_utc=start + timedelta(minutes=5), open=100, high=101, low=100, close=101, volume=0.0,
        volume_kind="absent", finalized=False, received_at_utc=start,
    )  # fmt: skip
    h.ctx.provisional = True
    out = h.engine.on_provisional(forming)
    assert [(e.event_type, e.payload["kind"], e.payload["imb"]) for e in out.events] == [
        ("alert", "press_buy_early", 1.0)
    ]
    assert (
        json.dumps(h.engine.snapshot(), sort_keys=True, allow_nan=False) == before
    )  # nothing moved
    assert (
        h.engine.on_provisional(forming).events[0].payload["kind"] == "press_buy_early"
    )  # and it is repeatable
    nothing = Harness(fp_at_zone_only=False, **NOHTF)
    assert (
        nothing.engine.on_provisional(forming).events == []
    )  # no confirmed ATR yet: no zones to judge against
    _ = math
