"""Features (hand-computed), NaN handling, session boundaries, anchors and the three baselines."""

import math
from datetime import date, timedelta

import pytest

from nifty.contracts import Bar
from nifty.engines.research.baselines import (
    anchor_cross_ema_order,
    ema_aligned_gap_reexpansion,
    ema_gap_reexpansion,
)  # fmt: skip
from nifty.engines.research.features import (
    ANCHOR_PROXY,
    ANCHOR_TWAP,
    ANCHOR_VWAP,
    Features,
    FeatureState,
)  # fmt: skip
from nifty.engines.research.params import ResearchParams
from tests.helpers import CAL, NOW

D1, D2 = date(2026, 11, 2), date(2026, 11, 3)
NaN = math.nan


def mk(
    d: date, i: int, o: float, h: float, lo: float, c: float, vol: float = 0.0, kind: str = "absent"
) -> Bar:
    start = CAL.session_bounds(d)[0] + timedelta(minutes=i)
    return Bar(
        instrument_id="csv:T", provider="csv", timeframe="1m", bar_start_utc=start,
        bar_end_utc=start + timedelta(minutes=1), open=o, high=h, low=lo, close=c, volume=vol,
        volume_kind=kind, received_at_utc=NOW,  # type: ignore[arg-type]
    )  # fmt: skip


def params(**kw: object) -> ResearchParams:
    return ResearchParams.model_validate(
        {"ema_fast": 2, "ema_slow": 3, "atr_len": 2, "rate_k": 1, **kw}
    )


def run(fs: FeatureState, bars: list[Bar]) -> list[Features]:
    return [fs.update(b, CAL) for b in bars]


def test_features_known_answers_by_hand() -> None:
    # TR (first bar high-low): 2, 2, 2 => ATR(2) = NaN, 2, 2; A is the PRIOR bar's ATR: NaN, NaN, 2
    # F (alpha 2/3, first-value seed): 10, 11.3333, 12.4444; S (alpha 1/2): 10, 11, 12
    # TWAP of hlc3 (10, 11.3333, 12.3333): V = 10, 10.6667, 11.2222
    fs = FeatureState(params())
    x = run(fs, [mk(D1, 0, 10, 11, 9, 10), mk(D1, 1, 10, 12, 10, 12), mk(D1, 2, 12, 13, 11, 13)])
    assert (
        math.isnan(x[0].a)
        and math.isnan(x[1].a)
        and math.isnan(x[0].d)
        and math.isnan(x[1].anchor_rate)
    )
    t = x[2]
    assert t.a == 2.0 and t.p == 13.0
    assert t.f == pytest.approx(12.4444444) and t.s == pytest.approx(12.0)
    assert t.v == pytest.approx(11.2222222) and t.anchor_kind == ANCHOR_TWAP
    assert (
        t.d == pytest.approx(0.8888889)
        and t.e == pytest.approx(0.2777778)
        and t.m == pytest.approx(0.2222222)
    )
    assert t.price_to_slow == pytest.approx(0.5) and t.fast_to_anchor == pytest.approx(0.6111111)
    assert t.slow_to_anchor == pytest.approx(0.3888889)
    # k = 1: ((P-V)[t] - (P-V)[t-1]) / (1 * A) = (1.7778 - 1.3333) / 2 ; gap: ((F-S)[t] - (F-S)[t-1]) / (1 * A)
    assert t.anchor_rate == pytest.approx(0.2222222) and t.gap_rate == pytest.approx(0.0555556)
    assert t.sign == 1 and t.prev_p == 12.0 and t.prev_v == pytest.approx(10.6666667)


def test_zero_or_invalid_atr_is_nan_never_infinity() -> None:
    fs = FeatureState(params())
    flat = run(
        fs, [mk(D1, i, 10, 10, 10, 10) for i in range(6)]
    )  # TR = 0 everywhere => ATR 0 => A invalid
    for x in flat:
        for name in (
            "a",
            "d",
            "e",
            "m",
            "price_to_slow",
            "fast_to_anchor",
            "anchor_rate",
            "gap_rate",
        ):
            v = getattr(x, name)
            assert math.isnan(v) and not math.isinf(v), name
    fs2 = FeatureState(params())
    out = run(fs2, [mk(D1, i, 10 + i, 11 + i, 9 + i, 10 + i) for i in range(5)])
    assert all(math.isfinite(out[-1].d) for _ in [0]) and not any(
        math.isinf(v) for v in (out[-1].d, out[-1].e, out[-1].m)
    )


def test_rates_and_anchor_do_not_cross_sessions() -> None:
    fs = FeatureState(params())
    d1 = run(fs, [mk(D1, i, 10, 11 + i, 9, 10 + i) for i in range(4)])
    d2 = run(fs, [mk(D2, i, 50, 51, 49, 50) for i in range(3)])
    assert (
        d1[3].anchor_rate == d1[3].anchor_rate and d1[3].gap_rate == d1[3].gap_rate
    )  # valid inside a session
    # first bar of day 2: not enough same-session history for k = 1: NaN even though day 1 exists
    assert math.isnan(d2[0].anchor_rate) and math.isnan(d2[0].gap_rate) and d2[0].new_session
    assert d2[0].v == pytest.approx(
        (51 + 49 + 50) / 3
    )  # the anchor restarted: day 1's bars are not in it
    assert d2[1].anchor_rate == d2[1].anchor_rate and not d2[1].new_session
    # EMAs are continuous (warm from earlier history), ATR too: A on day 2 bar 1 is day 1's last ATR
    assert d2[0].a == d2[0].a and d2[0].f == d2[0].f


def test_anchor_is_vwap_with_volume_twap_without_and_proxy_weighted_when_asked() -> None:
    vw = FeatureState(params())
    x = run(
        vw, [mk(D1, 0, 10, 12, 8, 10, 100, "exchange"), mk(D1, 1, 10, 16, 10, 16, 300, "exchange")]
    )
    # hlc3 = 10 and 14: sum(hlc3 * vol) / sum(vol) = (1000 + 4200) / 400 = 13
    assert x[1].v == pytest.approx(13.0) and x[1].anchor_kind == ANCHOR_VWAP
    px = FeatureState(params(anchor_proxy=True))
    a = px.update(mk(D1, 0, 10, 12, 8, 10), CAL, proxy_vol=1.0)  # hlc3 = 10
    b = px.update(mk(D1, 1, 10, 16, 10, 16), CAL, proxy_vol=3.0)  # hlc3 = 14: (10 + 42) / 4
    assert a.anchor_kind == ANCHOR_PROXY and b.v == pytest.approx(13.0)
    off = FeatureState(params())  # anchor_proxy False: the proxy is ignored and labelled TWAP
    assert off.update(mk(D1, 0, 10, 12, 8, 10), CAL, proxy_vol=5.0).anchor_kind == ANCHOR_TWAP


def test_features_state_roundtrips_through_json() -> None:
    import json

    fs = FeatureState(params())
    run(fs, [mk(D1, i, 10, 11 + i % 3, 9, 10 + i % 2) for i in range(8)])
    st = json.loads(json.dumps(fs.state(), allow_nan=False))
    other = FeatureState(params())
    other.load(st)
    nxt = mk(D1, 8, 10, 12, 9, 11)
    assert other.update(nxt, CAL) == fs.update(nxt, CAL)


# ---- baselines -----------------------------------------------------------------------------------
def feat(**kw: float) -> Features:
    base = dict(p=100.0, f=100.0, s=100.0, v=100.0, a=2.0, d=0.0, e=0.0, m=0.0, price_to_slow=0.0,
                fast_to_anchor=0.0, slow_to_anchor=0.0, anchor_rate=NaN, gap_rate=NaN, prev_gap_rate=NaN,
                prev_p=100.0, prev_v=100.0)  # fmt: skip
    base.update(kw)
    return Features(**base, anchor_kind=ANCHOR_TWAP, new_session=False, sign=0)


def test_anchor_cross_ema_order_trigger_and_non_trigger() -> None:
    long_ = feat(prev_p=99.0, prev_v=100.0, p=101.0, v=100.5, f=102.0, s=101.0)
    assert anchor_cross_ema_order(long_) == 1
    assert (
        anchor_cross_ema_order(feat(prev_p=100.0, prev_v=100.0, p=101.0, v=100.5, f=102.0, s=101.0))
        == 1
    )  # prev <= is inclusive
    assert (
        anchor_cross_ema_order(feat(prev_p=99.0, prev_v=100.0, p=101.0, v=100.5, f=101.0, s=102.0))
        == 0
    )  # EMA order disagrees
    assert (
        anchor_cross_ema_order(feat(prev_p=101.0, prev_v=100.0, p=102.0, v=100.5, f=102.0, s=101.0))
        == 0
    )  # already above
    assert (
        anchor_cross_ema_order(feat(prev_p=99.0, prev_v=100.0, p=99.5, v=100.5, f=102.0, s=101.0))
        == 0
    )  # no cross
    short = feat(prev_p=101.0, prev_v=100.0, p=99.0, v=99.5, f=98.0, s=99.0)
    assert anchor_cross_ema_order(short) == -1
    assert (
        anchor_cross_ema_order(feat(prev_p=NaN, prev_v=100.0, p=101.0, v=100.5, f=102.0, s=101.0))
        == 0
    )  # no history


def test_ema_gap_reexpansion_trigger_and_non_trigger() -> None:
    assert (
        ema_gap_reexpansion(feat(gap_rate=0.1, prev_gap_rate=0.0, p=101.0, f=100.0)) == 1
    )  # prior <= 0
    assert ema_gap_reexpansion(feat(gap_rate=0.1, prev_gap_rate=-0.2, p=101.0, f=100.0)) == 1
    assert (
        ema_gap_reexpansion(feat(gap_rate=0.1, prev_gap_rate=0.05, p=101.0, f=100.0)) == 0
    )  # already expanding
    assert (
        ema_gap_reexpansion(feat(gap_rate=0.1, prev_gap_rate=-0.2, p=100.0, f=100.0)) == 0
    )  # close must be > F
    assert ema_gap_reexpansion(feat(gap_rate=0.0, prev_gap_rate=-0.2, p=101.0, f=100.0)) == 0
    assert ema_gap_reexpansion(feat(gap_rate=-0.1, prev_gap_rate=0.0, p=99.0, f=100.0)) == -1
    assert ema_gap_reexpansion(feat(gap_rate=-0.1, prev_gap_rate=-0.3, p=99.0, f=100.0)) == 0
    assert (
        ema_gap_reexpansion(feat(gap_rate=0.1, prev_gap_rate=NaN, p=101.0, f=100.0)) == 0
    )  # NaN is never a trigger
    assert ema_gap_reexpansion(feat(gap_rate=NaN, prev_gap_rate=-1.0, p=101.0, f=100.0)) == 0


def test_aligned_variant_adds_only_the_ema_order_condition() -> None:
    base = dict(gap_rate=0.1, prev_gap_rate=-0.1, p=101.0, f=100.0)
    assert ema_aligned_gap_reexpansion(feat(**base, s=99.0)) == 1
    assert (
        ema_aligned_gap_reexpansion(feat(**base, s=101.0)) == 0
        and ema_gap_reexpansion(feat(**base, s=101.0)) == 1
    )
    bear = dict(gap_rate=-0.1, prev_gap_rate=0.1, p=99.0, f=100.0)
    assert ema_aligned_gap_reexpansion(feat(**bear, s=101.0)) == -1
    assert ema_aligned_gap_reexpansion(feat(**bear, s=99.0)) == 0
