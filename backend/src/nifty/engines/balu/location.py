"""Step 10 (L626-663): where price sits in the live zone map. Zones are scanned in array order and
later zones overwrite earlier ones (tap_* values); demand wins the location index."""

import math
from dataclasses import dataclass
from typing import Any

from nifty.contracts import PlotSpec
from nifty.engines.balu.steps import PLOT_SPECS, BarFrame, step
from nifty.engines.balu.zones import Zone

NaN = math.nan
PLOT_SPECS += [
    PlotSpec(name=n, pane="own")
    for n in ("next_up", "next_dn", "next_up_proj", "next_dn_proj", "loc_idx", "tap_demand_bot",
              "tap_supply_top", "zones_up", "zones_dn")
]  # fmt: skip


@dataclass
class Location:
    at_demand: bool = False
    at_supply: bool = False
    tap_demand_bot: float = NaN
    tap_supply_top: float = NaN
    tap_demand_c: float = NaN
    tap_supply_c: float = NaN
    next_up: float = NaN
    next_dn: float = NaN
    next_up_proj: bool = False
    next_dn_proj: bool = False
    zones_up: int = 0
    zones_dn: int = 0

    @property
    def loc_idx(self) -> int:
        return 0 if self.at_demand else 2 if self.at_supply else 1


def locate(zones: list[Zone], close: float, atr: float, zone_prox_atr: float) -> Location:
    loc = Location()
    prox = atr * zone_prox_atr
    for z in zones:
        if z.mitigated:
            continue
        if close <= z.top + prox and close >= z.bot - prox:
            if z.is_demand:
                loc.at_demand, loc.tap_demand_bot, loc.tap_demand_c = True, z.bot, z.center
            else:
                loc.at_supply, loc.tap_supply_top, loc.tap_supply_c = True, z.top, z.center
        if not z.is_demand and z.bot > close:
            loc.zones_up += 1
            if loc.next_up != loc.next_up or z.bot < loc.next_up:
                loc.next_up, loc.next_up_proj = z.bot, z.is_projected
        if z.is_demand and z.top < close:
            loc.zones_dn += 1
            if loc.next_dn != loc.next_dn or z.top > loc.next_dn:
                loc.next_dn, loc.next_dn_proj = z.top, z.is_projected
    return loc


@step(10)
def location(eng: Any, f: BarFrame) -> None:
    loc = locate(eng.slots["zones"].zones, f.bar.close, f.atr, eng.p.zone_prox_atr)
    f.extra["location"] = loc
    f.out.plots.update(
        next_up=loc.next_up, next_dn=loc.next_dn, next_up_proj=float(loc.next_up_proj),
        next_dn_proj=float(loc.next_dn_proj), loc_idx=float(loc.loc_idx),
        tap_demand_bot=loc.tap_demand_bot, tap_supply_top=loc.tap_supply_top,
        zones_up=float(loc.zones_up), zones_dn=float(loc.zones_dn),
    )  # fmt: skip
