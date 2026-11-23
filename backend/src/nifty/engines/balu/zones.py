"""Steps 7-8 (L433-566): zone housekeeping and rebuild. Zones keep CREATION ORDER (location
overwrites by array order). Overlays are event-sourced: id `z<seq>`, ver 0 on creation
(`meta.status` active|projected), a new ver with status `mitigated` and `t1` = that bar's end when
price closes through the zone, and a final `deleted` ver when it is dropped."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nifty.contracts import OverlayElement, PlotSpec
from nifty.engines.balu.levels import LevelPool
from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.steps import PLOT_SPECS, BarFrame, register_slot, step

PLOT_SPECS.append(PlotSpec(name="zones_size", pane="own"))

Emit = Callable[[OverlayElement], None]


@dataclass
class Zone:
    seq: int
    top: float
    bot: float
    center: float
    is_demand: bool
    is_projected: bool
    mitigated: bool
    t0: datetime  # created bar start (overlay t0)
    tier: int
    ver: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "seq": self.seq, "top": self.top, "bot": self.bot, "center": self.center,
            "is_demand": self.is_demand, "is_projected": self.is_projected,
            "mitigated": self.mitigated, "t0": self.t0.isoformat(), "tier": self.tier,
            "ver": self.ver,
        }  # fmt: skip

    @staticmethod
    def from_json(d: dict[str, Any]) -> "Zone":
        return Zone(**{**d, "t0": datetime.fromisoformat(d["t0"])})


def element(z: Zone, t1: datetime | None, deleted: bool = False) -> OverlayElement:
    status = "mitigated" if z.mitigated else "projected" if z.is_projected else "active"
    return OverlayElement(
        id=f"z{z.seq}", ver=z.ver, deleted=deleted, kind="zone", t0=z.t0, t1=t1, p0=z.top, p1=z.bot,
        style={"role": "demand" if z.is_demand else "supply", "dashed": z.is_projected},
        text=("Demand" if z.is_demand else "Supply") + (" (proj)" if z.is_projected else ""),
        meta={"status": status, "tier": z.tier, "top": z.top, "bot": z.bot, "center": z.center},
    )  # fmt: skip


class ZoneBook:
    def __init__(self) -> None:
        self.zones: list[Zone] = []
        self.next_seq = 1
        self.last_atr = math.nan  # last confirmed ATR (provisional pressure reads it)

    # ---- helpers ---------------------------------------------------------------------------
    def _make(
        self, center: float, is_demand: bool, projected: bool, tier: int, atr: float,
        p: BaluParams, mintick: float, now: datetime, emit: Emit,
    ) -> None:  # fmt: skip
        half = max(atr * p.zone_thick_atr, mintick * 4)
        z = Zone(
            self.next_seq,
            center + half,
            center - half,
            center,
            is_demand,
            projected,
            False,
            now,
            tier,
        )
        self.next_seq += 1
        self.zones.append(z)
        emit(element(z, None))

    def _drop(self, i: int, emit: Emit) -> None:
        z = self.zones.pop(i)
        z.ver += 1
        emit(element(z, None, deleted=True))

    # ---- step 7 ----------------------------------------------------------------------------
    def housekeeping(
        self, close: float, atr: float, structure_changed: bool, p: BaluParams,
        bar_end: datetime, emit: Emit,
    ) -> None:  # fmt: skip
        if not self.zones or not atr > 0:
            return
        far = atr * p.prune_atr
        for i in range(len(self.zones) - 1, -1, -1):
            z = self.zones[i]
            if not z.mitigated:
                through = close < z.bot if z.is_demand else close > z.top
                if through:
                    z.mitigated = True
                    z.ver += 1
                    if p.keep_mitigated:  # a spent zone ends where it broke
                        emit(element(z, bar_end))
            stale = z.is_projected and not z.mitigated and structure_changed
            if stale or (z.mitigated and not p.keep_mitigated) or abs(z.center - close) > far:
                self._drop(i, emit)

    # ---- step 8 ----------------------------------------------------------------------------
    def rebuild(
        self, close: float, atr: float, pool: LevelPool, p: BaluParams, mintick: float,
        now: datetime, emit: Emit,
    ) -> None:  # fmt: skip
        gap = max(atr * p.zone_thick_atr * 2.0, atr * 0.25)
        space = max(gap, atr * p.min_space_atr)  # v2.2: against EVERY live zone on that side
        used_up: list[float] = []
        used_dn: list[float] = []
        space_up: list[float] = []
        space_dn: list[float] = []
        have_up = have_dn = 0
        for z in self.zones:
            if z.mitigated:
                continue
            (space_dn if z.is_demand else space_up).append(z.center)
            if not z.is_demand and z.bot > close:
                have_up += 1
                used_up.append(z.center)
            if z.is_demand and z.top < close:
                have_dn += 1
                used_dn.append(z.center)
        tiers = p.zone_tiers

        def cap_of(k: int) -> float:
            return atr * (p.cap_base_atr + p.cap_step_atr * k)

        # v2.1 far-zone replacement: at most once per side per bar
        if have_up >= tiers:
            cand = pool.nearest_above(close, gap, space_up, space)
            far_up = max(used_up)
            if cand == cand and cand < far_up and far_up - close > cap_of(have_up - 1):
                self._drop_live(False, far_up, emit)
                used_up.remove(far_up)
                space_up.remove(far_up)
                have_up -= 1
        if have_dn >= tiers:
            cand = pool.nearest_below(close, gap, space_dn, space)
            far_dn = min(used_dn)
            if cand == cand and cand > far_dn and close - far_dn > cap_of(have_dn - 1):
                self._drop_live(True, far_dn, emit)
                used_dn.remove(far_dn)
                space_dn.remove(far_dn)
                have_dn -= 1
        for k in range(have_up, tiers):  # fill upward; k advances even if a tier is omitted
            cand = pool.nearest_above(close, gap, space_up, space)
            proj = cand != cand or cand - close > cap_of(k)
            lvl = close + cap_of(k) if proj else cand
            if proj and space_up:
                lvl = max(lvl, max(space_up) + space)
            if not proj or lvl <= close + cap_of(k):
                self._make(lvl, False, proj, k + 1, atr, p, mintick, now, emit)
                used_up.append(lvl)
                space_up.append(lvl)
        for k in range(have_dn, tiers):
            cand = pool.nearest_below(close, gap, space_dn, space)
            proj = cand != cand or close - cand > cap_of(k)
            lvl = close - cap_of(k) if proj else cand
            if proj and space_dn:
                lvl = min(lvl, min(space_dn) - space)
            if not proj or lvl >= close - cap_of(k):
                self._make(lvl, True, proj, k + 1, atr, p, mintick, now, emit)
                used_dn.append(lvl)
                space_dn.append(lvl)

    def _drop_live(self, is_demand: bool, center: float, emit: Emit) -> None:
        for i in range(len(self.zones) - 1, -1, -1):
            z = self.zones[i]
            if not z.mitigated and z.is_demand == is_demand and z.center == center:
                self._drop(i, emit)
                return

    def state(self) -> dict[str, Any]:
        return {
            "zones": [z.to_json() for z in self.zones], "next_seq": self.next_seq,
            "last_atr": None if self.last_atr != self.last_atr else self.last_atr,
        }  # fmt: skip

    def load(self, st: dict[str, Any]) -> None:
        self.zones = [Zone.from_json(d) for d in st["zones"]]
        self.next_seq = st["next_seq"]
        self.last_atr = math.nan if st["last_atr"] is None else st["last_atr"]


@register_slot("zones")
def make_zones(p: BaluParams) -> ZoneBook:
    return ZoneBook()


def _emit(f: BarFrame) -> Emit:
    return f.out.overlay_ops.append


@step(7)
def zone_housekeeping(eng: Any, f: BarFrame) -> None:
    book: ZoneBook = eng.slots["zones"]
    if f.atr == f.atr and f.atr > 0:
        book.last_atr = f.atr
    structure_changed = f.s_ph == f.s_ph or f.s_pl == f.s_pl  # chart-TF pivots only
    book.housekeeping(f.bar.close, f.atr, structure_changed, eng.p, f.bar.bar_end_utc, _emit(f))


@step(8)
def zone_rebuild(eng: Any, f: BarFrame) -> None:
    book: ZoneBook = eng.slots["zones"]
    if f.atr == f.atr and f.atr > 0 and f.in_session:
        book.rebuild(
            f.bar.close,
            f.atr,
            eng.slots["pool"],
            eng.p,
            eng.ctx.mintick,
            f.bar.bar_start_utc,
            _emit(f),
        )
    f.out.plots["zones_size"] = float(len(book.zones))
