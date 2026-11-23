import json
import math
from datetime import date, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nifty.contracts import Bar, EngineOutput, OverlayElement, TradeRecord
from nifty.engines.base import EngineNotReady, register_engine, unregister_engine
from nifty.engines.runner import RunResult, run_batch, run_incremental, run_with_restart
from nifty.marketdata.resample import resample
from tests.helpers import CAL, day_bars, wave
from tests.sma_cross_engine import SmaCross, registered

PARAMS = {"fast": 2, "slow": 3}


@pytest.fixture(autouse=True)
def _engine():  # type: ignore[no-untyped-def]
    with registered():
        yield


def view(r: RunResult) -> dict[str, object]:
    return {
        "bars": r.bars, "plots": r.plots, "events": r.events, "overlays": r.overlays,
        "panel": r.panel, "cfg": r.config_hash,
    }  # fmt: skip


def test_batch_run_shape_and_envelope() -> None:
    bars = wave(date(2026, 11, 2))
    r = run_batch("test.sma_cross", PARAMS, bars, "5m", source_id="snap_x")
    assert len(r.bars) == 75 and len(r.plots) == 75 and r.engine_version == "1"
    assert all(b.finalized and b.quality_flags == () for b in r.bars)
    assert r.plots[0][1]["fast"] is None  # na -> None, never NaN
    json.dumps([p for _, p in r.plots], allow_nan=False)
    ups = [e for e in r.events if e.payload["dir"] == "up"]
    assert ups and r.overlays and len(r.overlays) == len(ups)
    e = ups[0]
    assert (e.engine_id, e.source_id, e.timeframe, e.confirmed_or_provisional) == (
        "test.sma_cross", "snap_x", "5m", "confirmed")  # fmt: skip
    assert e.available_at_utc == e.bar_end_utc and e.config_hash == r.config_hash
    assert r.overlays[0].engine_id == "test.sma_cross"
    assert r.overlays[0].avail_at_utc is not None and r.overlays[0].avail_at_utc >= r.overlays[0].t0
    assert r.panel == {"rows": [{"label": "bars", "value": 75, "role": "neutral"}]}


def test_seq_distinguishes_same_type_events_on_one_bar() -> None:
    r = run_batch("test.sma_cross", PARAMS, wave(date(2026, 11, 2)), "5m")
    by_bar: dict[object, list[int]] = {}
    for e in r.events:
        if e.event_type == "signal" and e.payload["dir"] in ("down", "down-extra"):
            by_bar.setdefault(e.bar_start_utc, []).append(e.seq)
    assert by_bar and all(v == [0, 1] for v in by_bar.values())
    assert len({e.event_id for e in r.events}) == len(r.events)


def test_params_default_and_validation() -> None:
    bars = wave(date(2026, 11, 2), 60)
    assert run_batch("test.sma_cross", None, bars, "5m").params["fast"] == 3
    with pytest.raises(Exception, match="fastt"):
        run_batch("test.sma_cross", {"fastt": 1}, bars, "5m")


def test_unready_engine_refused_by_runner() -> None:
    with registered(ready=False):
        with pytest.raises(EngineNotReady):
            run_batch("test.sma_cross", PARAMS, wave(date(2026, 11, 2), 30), "5m")
        r = run_batch(
            "test.sma_cross", PARAMS, wave(date(2026, 11, 2), 30), "5m", allow_unready=True
        )
        assert r.bars


@st.composite
def ragged(draw: st.DrawFn) -> list[Bar]:
    days = draw(
        st.lists(
            st.sampled_from([date(2026, 11, 2), date(2026, 11, 3)]),
            min_size=1,
            max_size=2,
            unique=True,
        )
    )
    out: list[Bar] = []
    for d in sorted(days):
        base = wave(d, period=draw(st.integers(5, 40)))
        gone = draw(st.sets(st.integers(0, 374), max_size=40))
        out += [b for i, b in enumerate(base) if i not in gone]
    return out


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ragged(), st.sampled_from(["1m", "3m", "5m", "15m", "30m", "1h", "1d"]), st.data())
def test_batch_equals_incremental_equals_restart(
    bars: list[Bar], tf: str, data: st.DataObject
) -> None:
    batch = run_batch("test.sma_cross", PARAMS, bars, tf, source_id="s")
    inc = run_incremental("test.sma_cross", PARAMS, bars, tf, source_id="s")
    # chart bars are equal in every field (flags are stripped, finalized, bar_end included)
    assert view(batch) == view(inc)
    if batch.bars:
        cut = data.draw(st.integers(1, len(batch.bars)))
        assert view(
            run_with_restart("test.sma_cross", PARAMS, bars, tf, cut=cut, source_id="s")
        ) == view(batch)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ragged(), st.sampled_from(["5m", "15m"]), st.data(), st.integers(0, 10_000))
def test_prefix_immunity(bars: list[Bar], tf: str, data: st.DataObject, seed: int) -> None:
    base = run_batch("test.sma_cross", PARAMS, bars, tf)
    if len(base.bars) < 2:
        return
    k = data.draw(st.integers(0, len(base.bars) - 2))
    boundary = base.bars[k].bar_end_utc
    changed = [
        b if b.bar_start_utc < boundary else _alter(b, seed + i) for i, b in enumerate(bars)
    ]  # same timestamps, different prices, only AFTER the boundary
    other = run_batch("test.sma_cross", PARAMS, changed, tf)
    assert [b.bar_start_utc for b in other.bars] == [b.bar_start_utc for b in base.bars]
    assert other.plots[: k + 1] == base.plots[: k + 1]
    cutoff = base.bars[k].bar_start_utc
    assert [e for e in other.events if e.bar_start_utc <= cutoff] == [
        e for e in base.events if e.bar_start_utc <= cutoff
    ]
    assert [o for o in other.overlays if o.t0 <= cutoff] == [
        o for o in base.overlays if o.t0 <= cutoff
    ]


def _alter(b: Bar, seed: int) -> Bar:
    c = 24000 + (seed * 37) % 2000
    return b.model_copy(update={"open": c, "high": c + 2, "low": c - 2, "close": c + 1})


def test_provisional_never_changes_confirmed_state() -> None:
    bars = wave(date(2026, 11, 2), 120)
    plain = run_incremental("test.sma_cross", PARAMS, bars, "5m")
    prov = run_incremental("test.sma_cross", PARAMS, bars, "5m", provisional=True)
    assert view(plain) == view(prov)  # on_provisional left every confirmed output untouched
    assert prov.provisional and not plain.provisional
    p = prov.provisional[3]
    assert all(
        e.confirmed_or_provisional == "provisional" for x in prov.provisional for e in x["events"]
    )
    assert p["available_at_utc"] < p["events"][0].bar_end_utc if p["events"] else True


def test_engine_snapshot_unchanged_by_on_provisional() -> None:
    from nifty.contracts import Instrument
    from nifty.engines.context import EngineContext
    from tests.sma_cross_engine import SmaCross, SmaCrossParams

    bars = wave(date(2026, 11, 2), 60)
    ctx = EngineContext(
        Instrument(instrument_id="csv:T", provider="csv", tradingsymbol="T", tick_size=0.05),
        "5m",
        CAL,
    )
    eng = SmaCross(SmaCrossParams(fast=2, slow=3), ctx)
    for b in bars[:50]:
        ctx.append_1m(b)
    for cb in resample(bars[:50], "5m", CAL):
        eng.on_bar(cb)
    before = json.dumps(eng.snapshot(), sort_keys=True)
    ctx.append_1m(bars[50])
    partial = resample(bars[50:51], "5m", CAL)[0]
    ctx.provisional = True
    for _ in range(3):
        eng.on_provisional(partial)
    assert json.dumps(eng.snapshot(), sort_keys=True) == before


def test_restart_roundtrip_rejects_non_json_snapshots() -> None:
    from nifty.engines.base import unregister_engine
    from tests.sma_cross_engine import SmaCross

    class Bad(SmaCross):
        id = "test.bad_snapshot"

        def snapshot(self):  # type: ignore[no-untyped-def]
            return {"x": math.nan}

    from nifty.engines.base import register_engine

    register_engine(Bad)
    try:
        with pytest.raises(ValueError):
            run_with_restart("test.bad_snapshot", PARAMS, wave(date(2026, 11, 2), 60), "5m", cut=2)
    finally:
        unregister_engine("test.bad_snapshot")


@pytest.mark.parametrize("holes", [frozenset(), frozenset({3, 4, 9, 20, 21, 22})])
def test_ctx_buffer_only_has_bars_up_to_the_current_chart_bar(holes: frozenset[int]) -> None:
    """With holes a bucket is proven final only by a LATER 1m bar; that bar must not be in the
    buffer yet when on_bar runs (it is in the future), in batch and in incremental mode."""
    seen: list[int] = []
    from tests.sma_cross_engine import SmaCross

    orig = SmaCross.on_bar

    def spy(self, b):  # type: ignore[no-untyped-def]
        seen.append(len(self.ctx._bars))
        return orig(self, b)

    SmaCross.on_bar = spy  # type: ignore[method-assign]
    try:
        bars = [b for i, b in enumerate(wave(date(2026, 11, 2), 30)) if i not in holes]
        run_batch("test.sma_cross", PARAMS, bars, "5m")
        batch_seen, seen[:] = list(seen), []
        run_incremental("test.sma_cross", PARAMS, bars, "5m")
    finally:
        SmaCross.on_bar = orig  # type: ignore[method-assign]
    assert batch_seen == seen
    # every chart bar sees exactly the 1m bars that start before its own end
    ends = [
        CAL.session_bounds(date(2026, 11, 2))[0] + timedelta(minutes=5 * (k + 1)) for k in range(6)
    ]
    assert (
        batch_seen
        == [
            sum(b.bar_start_utc < e for b in bars)
            for e in ends
            if any(b.bar_start_utc < e for b in bars)
        ][: len(batch_seen)]
    )


def test_gap_bucket_is_final_only_once_a_later_bar_proves_it() -> None:
    bars = day_bars(date(2026, 11, 2))
    holey = [b for i, b in enumerate(bars[:20]) if i not in (3, 4)]  # bucket 0-4 loses its tail
    inc = run_incremental("test.sma_cross", PARAMS, holey, "5m")
    assert [b.bar_start_utc for b in inc.bars] == [
        b.bar_start_utc for b in run_batch("test.sma_cross", PARAMS, holey, "5m").bars
    ][: len(inc.bars)]
    assert inc.bars[0].close == bars[2].close  # last present minute of the first bucket


class _NanOverlayEngine(SmaCross):
    """Emits an overlay with na edges and (when asked) a trade, to check NaN never leaves the runner."""

    id = "test.nan_overlay"
    bad_trade = False

    def on_bar(self, bar: Bar) -> EngineOutput:
        out = super().on_bar(bar)
        out.overlay_ops.append(
            OverlayElement(
                id=f"z{bar.bar_start_utc.isoformat()}", kind="zone", t0=bar.bar_start_utc,
                p0=bar.low, p1=math.nan, style={"alpha": math.nan, "role": "demand"},
                meta={"top": math.nan, "tiers": [1.0, math.nan]},
            )
        )  # fmt: skip
        out.trades.append(
            TradeRecord(
                trade_id=f"t{self.n}", engine_id=self.id, instrument_id="csv:T", side="long",
                entry_time=bar.bar_start_utc, entry_px=1.0, exit_time=bar.bar_end_utc, exit_px=2.0,
                exit_reason="TIME", gross_pts=math.nan if self.bad_trade else 1.0,
                net_pts=1.0, r_multiple=math.nan,
            )
        )  # fmt: skip
        return out


def test_nan_in_overlays_and_trades_is_sanitised() -> None:
    register_engine(_NanOverlayEngine)
    try:
        bars = wave(date(2026, 11, 2), 60)
        r = run_batch("test.nan_overlay", PARAMS, bars, "5m")
        assert r.overlays and all(o.p1 is None and o.p0 is not None for o in r.overlays)
        o = r.overlays[0]
        assert o.style["alpha"] is None and o.meta["top"] is None and o.meta["tiers"] == [1.0, None]
        assert r.trades and all(t.r_multiple is None for t in r.trades)  # optional na -> None
        for o in r.overlays:
            json.loads(o.model_dump_json())  # strict JSON round trip == in-memory value
            assert type(o).model_validate_json(o.model_dump_json()) == o
        inc = run_incremental("test.nan_overlay", PARAMS, bars, "5m")
        assert (inc.overlays, inc.trades) == (r.overlays, r.trades)
        _NanOverlayEngine.bad_trade = True
        with pytest.raises(ValueError, match="NaN in a required field"):
            run_batch("test.nan_overlay", PARAMS, bars, "5m")
    finally:
        _NanOverlayEngine.bad_trade = False
        unregister_engine("test.nan_overlay")
