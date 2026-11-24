"""Steps 5-6: session cumulative delta, flowReady gating, flow z (population stdev, warm-up 0),
divergence confirmed `divPivotLen` bars late (L360-430)."""

import math
from collections.abc import Sequence
from typing import Any

import pytest

from tests.unit.engines.balu.helpers import D1, D2, OHLC, Harness

NOHTF: dict[str, Any] = {"use_htf_levels": False}


def up() -> OHLC:  # range 2, close at the high: closePos 1 -> delta +2 (Price Action source)
    return (100, 101, 99, 101)


def dn() -> OHLC:  # close at the low: delta -2
    return (100, 101, 99, 99)


def test_cvd_resets_each_session_and_the_line_is_gated_by_flow_ready() -> None:
    h = Harness(**NOHTF)
    h.day(D1, [up() if i % 2 == 0 else dn() for i in range(14)])  # cvd: 2 0 2 0 ...
    h.day(D2, [up(), dn()])
    cvd = h.plot("cvd")
    assert cvd[:4] == [2.0, 0.0, 2.0, 0.0]
    assert cvd[14:] == [2.0, 0.0]  # a new session restarts the sum: not 0 + 2 or 2 + 2
    ready = h.plot("flow_ready")
    # bar 1: cvdHi == cvdLo (no range yet); bars 2..9: dayLen < flowWarmBars = 10; ready from bar 10
    assert ready[:9] == [0.0] * 9 and ready[9:14] == [1.0] * 5
    ml = h.plot("moving_line")
    assert all(math.isnan(x) for x in ml[:9])
    # sessLo = 99, priceSpan = 101 - 99 = 2, cvdLo = 0, cvdHi = 2: bar 10 (cvd 0) -> 99; bar 11 (cvd 2) -> 101
    assert ml[9] == 99.0 and ml[10] == 101.0 and ml[11] == 99.0
    assert math.isnan(ml[14])  # day 2 bar 1: dayLen 1 < 10


def test_flow_z_is_zero_in_warmup_then_uses_a_population_stdev_over_100_slopes() -> None:
    n = 110  # two sessions: the EMA is continuous across them, cvd is not
    specs = [up() if g % 2 == 0 else dn() for g in range(n)]
    h = Harness(**NOHTF)
    h.day(D1, specs[:75])
    h.day(D2, specs[75:])
    # independent re-derivation from Pine: ema(barDelta, 5) seeded with the first value, summed over 5,
    # stdev over 100 slopes (population)
    delta = [2.0 if g % 2 == 0 else -2.0 for g in range(n)]
    ema, e = [], delta[0]
    for t, d in enumerate(delta):
        e = d if t == 0 else e + (2 / 6) * (d - e)
        ema.append(e)
    slope = [sum(ema[t - 4 : t + 1]) if t >= 4 else math.nan for t in range(n)]
    z = h.plot("flow_z")
    assert (
        z[:103] == [0.0] * 103
    )  # slopeSd is NaN until 100 slopes exist (first slope at bar 5): z = 0, not NaN
    for t in (103, 104, 109):
        win = slope[t - 99 : t + 1]
        mean = sum(win) / 100
        sd = math.sqrt(sum((x - mean) ** 2 for x in win) / 100)  # population, not sample
        assert z[t] == pytest.approx(slope[t] / sd)
        assert h.plot("flow_state")[t] == (1.0 if z[t] > 0.3 else -1.0 if z[t] < -0.3 else 0.0)


def pattern(highs: Sequence[float], deltas: Sequence[float]) -> list[OHLC]:
    out = []
    for hi, d in zip(highs, deltas, strict=True):
        lo = hi - 2
        out.append(
            (lo + 1, hi, lo, lo + (d + 2) / 2)
        )  # range 2, delta = 2 * (2 * closePos - 1) = d
    return out


H1 = [100, 101, 105, 101, 100, 101, 102, 108, 102, 101, 100, 99]
D_1 = [
    2,
    2,
    2,
    -2,
    -2,
    -2,
    -2,
    0,
    0,
    0,
    0,
    0,
]  # cvd: 2 4 6 4 2 0 -2 -2 -2 ...: 6 at the first pivot, -2 at the second


def test_bearish_divergence_is_signalled_on_the_confirming_bar_not_back_dated() -> None:
    h = Harness(div_pivot_len=2, **NOHTF)
    h.day(D1, pattern(H1, D_1))
    events = [
        (i, e) for i, o in enumerate(h.outs) for e in o.events if e.event_type == "divergence"
    ]
    # pivot highs: bar 3 (105, cvd 6) confirmed at bar 5 (no earlier pivot: no signal), bar 8
    # (108 > 105, cvd -2 < 6) confirmed at bar 10 => BEARISH divergence on bar 10, two bars after the swing
    assert [(i, e.event_type, e.payload["side"]) for i, e in events] == [(9, "divergence", "bear")]
    pay = events[0][1].payload
    assert (
        pay["pivot_bar_start"] == h.starts[7].isoformat()
        and pay["known_bar_start"] == h.starts[9].isoformat()
    )
    assert h.starts[9] - h.starts[7] == 2 * (h.starts[1] - h.starts[0])  # lag = divPivotLen bars


def test_divergence_memory_resets_on_a_new_session() -> None:
    h = Harness(div_pivot_len=2, **NOHTF)
    h.day(D1, pattern(H1, D_1))
    # day 2: a HIGHER pivot (110 > 108) with a LOWER cvd (-6 < -2): would be bearish if yesterday's
    # pivot survived; lastPH is NaN again on the new session, so nothing fires
    h.day(D2, pattern([100, 101, 110, 101, 100], [-2] * 5))
    assert [e for o in h.outs[12:] for e in o.events if e.event_type == "divergence"] == []


def test_divergence_is_off_with_show_div_false_and_needs_dayLen_above_2L() -> None:
    off = Harness(div_pivot_len=2, show_div=False, **NOHTF)
    off.day(D1, pattern(H1, D_1))
    assert [e for o in off.outs for e in o.events if e.event_type == "divergence"] == []
