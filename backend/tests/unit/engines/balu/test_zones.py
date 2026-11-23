"""Zone housekeeping/rebuild and location, from the Pine rules (L433-566, L626-663), with atr = 2:
half = max(2*0.35, 4*0.05) = 0.7, gap = max(1.4, 0.5) = 1.4, space = max(gap, 2*1.0) = 2.0,
cap(k) = 2 * (2.5 + 2.5k) = 5, 10, ..."""

from datetime import UTC, datetime
from typing import Any

from nifty.contracts import OverlayElement
from nifty.engines.balu.levels import LevelPool
from nifty.engines.balu.location import locate
from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.zones import Zone, ZoneBook

T0 = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 2, 4, 5, tzinfo=UTC)
ATR = 2.0


def params(**kw: Any) -> BaluParams:
    return BaluParams.model_validate(kw)


def pool(*levels: float) -> LevelPool:
    p = LevelPool()
    p.prices, p.is_high = list(levels), [True] * len(levels)  # flags are ignored by the queries
    return p


def rebuild(book: ZoneBook, close: float, pl: LevelPool, **kw: Any) -> list[OverlayElement]:
    out: list[OverlayElement] = []
    book.rebuild(close, ATR, pl, params(**kw), 0.05, T0, out.append)
    return out


def zone(seq: int, center: float, demand: bool, proj: bool = False, mit: bool = False) -> Zone:
    return Zone(seq, center + 0.7, center - 0.7, center, demand, proj, mit, T0, 1)


def test_rebuild_fills_tiers_with_half_thickness_gap_space_and_caps() -> None:
    book = ZoneBook()
    ops = rebuild(book, 100.0, pool(105.0, 95.0))
    got = [(z.seq, z.center, z.is_demand, z.is_projected, z.tier) for z in book.zones]
    # up: tier 1 = real level 105 (5 away, not beyond cap 5); tier 2 = 105 is taken (|105-105| <= 2),
    # so projected at close + cap(1) = 110 (and >= 105 + space). Down mirrors: 95 then projected 90.
    assert got == [(1, 105.0, False, False, 1), (2, 110.0, False, True, 2),
                   (3, 95.0, True, False, 1), (4, 90.0, True, True, 2)]  # fmt: skip
    z = book.zones[0]
    assert (z.top, z.bot) == (105.7, 104.3)  # center +- max(atr*0.35, 4*mintick)
    assert [(o.id, o.ver, o.deleted, o.kind) for o in ops] == [
        (f"z{i}", 0, False, "zone") for i in (1, 2, 3, 4)
    ]
    assert ops[0].meta["status"] == "active" and ops[1].meta["status"] == "projected"
    assert ops[0].style["role"] == "supply" and ops[2].style["role"] == "demand"
    assert ops[1].text == "Supply (proj)" and ops[2].text == "Demand" and ops[0].t1 is None
    assert (
        rebuild(book, 100.0, pool(105.0, 95.0)) == []
    )  # nothing missing: a second pass changes nothing


def test_half_thickness_has_a_floor_of_four_mintick() -> None:
    book = ZoneBook()
    out: list[OverlayElement] = []
    book.rebuild(100.0, 0.1, pool(), params(), 0.05, T0, out.append)  # atr*0.35 = 0.035 < 0.2
    assert all(abs((z.top - z.bot) / 2 - 0.2) < 1e-12 for z in book.zones)


def test_an_unreachable_projected_tier_is_omitted_but_k_still_advances() -> None:
    book = ZoneBook()
    book.zones, book.next_seq = (
        [zone(1, 109.0, False)],
        2,
    )  # one live supply already above (bot 108.3 > 100)
    rebuild(book, 100.0, pool())
    # tier k=1 up: proj lvl = max(100 + 10, 109 + 2) = 111 > close + cap(1) = 110 => omitted
    assert [(z.center, z.is_demand) for z in book.zones] == [
        (109.0, False),
        (95.0, True),
        (90.0, True),
    ]


def test_far_zone_replacement_happens_once_per_side_per_bar() -> None:
    book = ZoneBook()
    book.zones, book.next_seq = (
        [zone(1, 103.0, False), zone(2, 140.0, False), zone(3, 150.0, False)],
        4,
    )
    ops = rebuild(book, 100.0, pool(106.0))  # 106 is >= space away from 103: a usable candidate
    # have_up = 3 >= 2 tiers: cand 106 < farUp 150 and 150 - 100 > cap(2) = 20 => drop ONLY the 150 zone
    assert [(o.id, o.deleted) for o in ops if o.deleted] == [("z3", True)]
    assert [z.center for z in book.zones if not z.is_demand] == [
        103.0,
        140.0,
    ]  # 140 survives this bar
    book2 = ZoneBook()
    book2.zones, book2.next_seq = [zone(1, 103.0, False), zone(2, 140.0, False)], 3
    ops2 = rebuild(book2, 100.0, pool(106.0))
    # 140 replaced (40 > cap(1) = 10), have_up drops to 1, tier k=1 fills with the real level 106
    assert [o.id for o in ops2 if o.deleted] == ["z2"]
    assert sorted(z.center for z in book2.zones if not z.is_demand) == [103.0, 106.0]
    book3 = ZoneBook()
    book3.zones, book3.next_seq = [zone(1, 97.0, True), zone(2, 60.0, True)], 3
    rebuild(book3, 100.0, pool(94.0))  # mirror: farDn = 60, cand 94 > 60, 100 - 60 > cap(1)
    assert sorted(z.center for z in book3.zones if z.is_demand) == [94.0, 97.0]


def test_mitigation_keep_mitigated_and_drop() -> None:
    def book_with() -> ZoneBook:
        b = ZoneBook()
        b.zones, b.next_seq = [zone(1, 105.0, False), zone(2, 110.0, False, proj=True)], 3
        return b

    out: list[OverlayElement] = []
    b = book_with()
    b.housekeeping(106.0, ATR, False, params(), T1, out.append)  # 106 > supply top 105.7: spent
    assert [(o.id, o.deleted) for o in out] == [("z1", True)] and [z.seq for z in b.zones] == [2]
    out2: list[OverlayElement] = []
    k = book_with()
    k.housekeeping(106.0, ATR, False, params(keep_mitigated=True), T1, out2.append)
    assert [(o.id, o.meta["status"], o.t1) for o in out2] == [
        ("z1", "mitigated", T1)
    ]  # ends where it broke
    assert [z.seq for z in k.zones] == [1, 2] and k.zones[0].mitigated and out2[0].ver == 1
    # a mitigated zone is skipped by the rebuild scan and by location
    assert locate(k.zones, 105.5, ATR, 0.35).at_supply is False


def test_stale_projected_zone_gives_way_to_confirmed_structure() -> None:
    b = ZoneBook()
    b.zones, b.next_seq = (
        [zone(1, 105.0, False), zone(2, 110.0, False, proj=True), zone(3, 90.0, True, proj=True)],
        4,
    )
    out: list[OverlayElement] = []
    b.housekeeping(100.0, ATR, False, params(), T1, out.append)
    assert out == [] and len(b.zones) == 3  # no new structure: projected zones stay
    b.housekeeping(100.0, ATR, True, params(), T1, out.append)  # sPH/sPL confirmed this bar
    assert sorted(o.id for o in out) == ["z2", "z3"] and [z.seq for z in b.zones] == [
        1
    ]  # only projected ones


def test_zones_beyond_prune_distance_are_dropped() -> None:
    b = ZoneBook()
    b.zones, b.next_seq = (
        [zone(1, 105.0, False), zone(2, 112.0, False), zone(3, 94.0, True), zone(4, 89.0, True)],
        5,
    )
    out: list[OverlayElement] = []
    b.housekeeping(100.0, ATR, False, params(prune_atr=3.0), T1, out.append)  # far = 6
    assert sorted(o.id for o in out) == ["z2", "z4"] and [z.seq for z in b.zones] == [1, 3]


def test_zones_with_invalid_atr_are_left_alone() -> None:
    b = ZoneBook()
    b.zones = [zone(1, 500.0, False)]
    out: list[OverlayElement] = []
    b.housekeeping(100.0, float("nan"), True, params(), T1, out.append)
    assert out == [] and len(b.zones) == 1


def test_location_later_zones_overwrite_and_demand_wins() -> None:
    zs = [
        Zone(1, 101.0, 99.0, 100.0, True, False, False, T0, 1),
        Zone(2, 101.5, 99.5, 100.5, True, False, False, T0, 1),
        Zone(3, 104.0, 102.0, 103.0, False, True, False, T0, 2),
        Zone(4, 106.0, 105.0, 105.5, False, False, False, T0, 1),
    ]
    loc = locate(zs, 100.8, ATR, 0.35)  # prox = 0.7
    assert loc.at_demand and not loc.at_supply and loc.loc_idx == 0
    assert (loc.tap_demand_bot, loc.tap_demand_c) == (99.5, 100.5)  # zone 2 overwrote zone 1
    assert (loc.next_up, loc.next_up_proj) == (
        102.0,
        True,
    )  # lowest supply bot above price, projected
    assert loc.next_dn != loc.next_dn  # no demand top below 100.8 (101 and 101.5 are above)
    assert (loc.zones_up, loc.zones_dn) == (2, 0)
    mid = locate(zs, 98.0, ATR, 0.35)  # 98 < 99 - 0.7: not at demand
    assert mid.loc_idx == 1 and (mid.next_up, mid.next_up_proj) == (102.0, True)
    sup = locate(zs, 104.5, ATR, 0.35)  # inside zone 3 and zone 4's proximity: the later one wins
    assert (
        sup.at_supply
        and sup.loc_idx == 2
        and (sup.tap_supply_top, sup.tap_supply_c) == (106.0, 105.5)
    )
    assert sup.next_dn == 101.5 and (sup.next_up, sup.next_up_proj) == (
        105.0,
        False,
    )  # highest demand top
    both = locate(
        [zs[0], Zone(9, 101.5, 99.5, 100.6, False, False, False, T0, 1)], 100.5, ATR, 0.35
    )
    assert both.at_demand and both.at_supply and both.loc_idx == 0  # demand wins the index


def test_zone_book_state_roundtrip() -> None:
    import json

    b = ZoneBook()
    rebuild(b, 100.0, pool(105.0, 95.0))
    b.last_atr = ATR
    st = json.loads(json.dumps(b.state(), allow_nan=False))
    c = ZoneBook()
    c.load(st)
    assert c.zones == b.zones and c.next_seq == b.next_seq == 5 and c.last_atr == ATR
    fresh = ZoneBook()
    assert fresh.state()["last_atr"] is None  # NaN is serialised as None
