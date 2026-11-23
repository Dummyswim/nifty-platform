"""NVS rules on hand-built 5m bars (docs/pine/NVS.md). Levels are read from the signal event so
the tail bars are expressed relative to entry / stop / target / risk."""

from datetime import date, timedelta
from typing import Any

import pytest

from nifty.contracts import Bar, EngineOutput, Instrument, TradeRecord
from nifty.engines.context import EngineContext
from nifty.engines.nvs import NvsParams, NvsScalper
from tests.helpers import CAL, bar

INST = Instrument(instrument_id="csv:T", provider="csv", tradingsymbol="T", tick_size=0.05)
D1, D2 = date(2026, 11, 2), date(2026, 11, 3)
# Relaxed so a synthetic ramp trades; risk is forced wide so exit rules can be isolated.
BASE: dict[str, Any] = dict(
    use_rsi=False, warmup_bars=1, min_sess_bars=1, atr_len=3, min_speed_atr=0.0,
    max_dev_atr=9.0, min_tgt_cost_x=0.0, cost_bps=0.0, commission_pct=0.0,
    max_trades_day=1, min_risk_atr=6.0, ext_atr=50.0, exit_vwap_buf_atr=50.0,
    max_hold_bars=99, flat_hm=1530,
)  # fmt: skip
Row = tuple[float, float, float, float]
RAMP: list[Row] = [
    (25000 + 2 * i - 1.5, 25000 + 2 * i + 0.3, 25000 + 2 * i - 1.8, 25000 + 2 * i) for i in range(6)
]  # the 6th bar (index 5) is the signal bar


class Run:
    def __init__(self, rows: list[Row], d: date = D1, **kw: Any) -> None:
        self.p = NvsParams(**{**BASE, **kw})
        self.e = NvsScalper(self.p, EngineContext(INST, "5m", CAL))
        self.outs: list[EngineOutput] = []
        self.feed(rows, d)

    def feed(self, rows: list[Row], d: date, first: int = 0) -> None:
        open_, _ = CAL.session_bounds(d)
        for i, (o, h, lo, c) in enumerate(rows, start=first):
            b = bar(
                open_ + timedelta(minutes=5 * i), o, h, lo, c, 0.0, tf="5m", volume_kind="absent"
            )
            self.outs.append(self.e.on_bar(b))

    def events(self, kind: str) -> list[dict[str, Any]]:
        return [ev.payload for o in self.outs for ev in o.events if ev.event_type == kind]

    @property
    def trades(self) -> list[TradeRecord]:
        return [t for o in self.outs for t in o.trades]


def levels() -> tuple[float, float, float, float]:
    sig = Run(RAMP).events("signal")[0]
    return sig["close"], sig["stop"], sig["target"], sig["risk_pts"]


def tail(*rows: Row, **kw: Any) -> Run:
    return Run(RAMP + list(rows), **kw)


def test_signal_event_and_levels() -> None:
    r = Run(RAMP)
    (sig,) = r.events("signal")
    close, stop, tgt, risk = levels()
    assert sig["side"] == "BUY" and close == 25010.0
    assert stop == pytest.approx(round((close - risk) / 0.05) * 0.05)  # mintick-rounded
    assert tgt == pytest.approx(round((close + 1.5 * risk) / 0.05) * 0.05)
    assert sig["why"].startswith("RSI OFF | TWAP spread")
    assert r.e.panel() is not None


def test_target_hit_on_fill_bar() -> None:
    entry = 25010.5  # next open
    _, stop, tgt, _ = levels()
    r = tail((entry, tgt + 1, entry - 0.5, tgt))
    (t,) = r.trades
    assert (t.exit_reason, t.exit_px, t.entry_px) == ("TP", tgt, entry) and t.bars_held == 1
    assert [e["reason"] for e in r.events("exit")] == ["TP"]


def test_stop_loss() -> None:
    entry = 25010.5
    _, stop, _, _ = levels()
    r = tail((entry, entry + 0.5, stop - 1, stop - 0.5))
    (t,) = r.trades
    assert (t.exit_reason, t.exit_px) == ("SL", stop)
    assert t.r_multiple is not None and t.r_multiple < -0.9


def test_break_even_ratchet_then_be_stop() -> None:
    entry = 25010.5
    _, stop, tgt, risk = levels()
    up = (entry, entry + 1.05 * risk, entry - 0.1, entry + risk)  # mfe >= 1R, target not hit
    r = tail(up, (entry + 1, entry + 2, entry - 1, entry))
    (upd,) = r.events("stop_update")
    be = entry + 0.05 * risk  # costBps = 0
    assert upd["stop"] == pytest.approx(be)
    (t,) = r.trades
    assert t.exit_reason == "BE_STOP" and t.exit_px == pytest.approx(be)
    # ratchet applies from the NEXT bar: the stop plot on the ratchet bar is still the new level
    assert r.outs[6].plots["stop"] == pytest.approx(be)


def test_vwap_loss_exits_at_next_open() -> None:
    entry = 25010.5
    _, stop, _, _ = levels()
    r = tail(
        (entry, entry + 0.5, entry - 0.2, entry),
        (entry, entry + 0.1, stop + 1, stop + 1.5),  # below the VWAP, above the stop
        (stop + 2, stop + 3, stop + 1.5, stop + 2),
        exit_vwap_buf_atr=0.1,
    )  # fmt: skip
    (t,) = r.trades
    assert t.exit_reason == "VWAP_LOSS" and t.exit_px == stop + 2  # open of bar 8


def test_stretch_stall() -> None:
    entry = 25010.5
    r = tail(
        (entry, entry + 4, entry - 0.2, entry + 3),
        (entry + 3, entry + 3.2, entry + 1, entry + 2),  # far from VWAP, close lower
        (entry + 2, entry + 3, entry + 1, entry + 2.5),
        ext_atr=0.5,
    )  # fmt: skip
    (t,) = r.trades
    assert t.exit_reason == "STRETCH_STALL" and t.exit_px == entry + 2


def test_time_exit() -> None:
    entry = 25010.5
    flat: Row = (entry, entry + 0.5, entry - 0.5, entry)
    r = tail(flat, flat, flat, max_hold_bars=2)
    (t,) = r.trades
    assert t.exit_reason == "TIME" and t.bars_held == 2  # bars 6-7 held; exits at bar 8 open


def test_eod_closes_on_this_bars_close() -> None:
    entry = 25010.5
    flat: Row = (entry, entry + 0.5, entry - 0.5, entry + 0.2)
    r = tail(flat, flat, flat, flat_hm=1000)  # bar 8 ends 10:00
    (t,) = r.trades
    assert t.exit_reason == "EOD" and t.exit_px == entry + 0.2
    assert t.exit_time == r.e.ctx.calendar.session_bounds(D1)[0] + timedelta(minutes=45)


def test_rejects_wide_stop_and_cheap_target() -> None:
    wide = RAMP[:-1] + [(25008.5, 25010.3, 25000.0, 25010.0)]  # rawRisk >> 1.8 ATR
    assert Run(wide, min_risk_atr=0.7).events("signal") == []
    cheap = Run(RAMP, min_risk_atr=0.7, min_tgt_cost_x=2.5, cost_bps=2.5)
    assert cheap.events("signal") == []  # 1.5R target < 2.5x costs
    assert Run(RAMP, min_risk_atr=0.7).events("signal")  # control: accepted without the cost rule


def test_max_trades_per_day_and_cooldown() -> None:
    rows = RAMP + [
        (25012 + 2 * i, 25012.5 + 2 * i, 25011.5 + 2 * i, 25012.2 + 2 * i) for i in range(8)
    ]
    one = Run(rows, max_trades_day=1, min_risk_atr=0.7)
    assert len(one.events("signal")) == 1
    many = Run(rows, max_trades_day=6, min_risk_atr=0.7, cooldown_bars=0)
    assert len(many.events("signal")) >= 2


def test_session_end_with_stale_in_pos() -> None:
    entry = 25010.5
    flat: Row = (entry, entry + 0.5, entry - 0.5, entry + 0.2)
    r = tail(flat, flat)  # day 1 data stops with the position still open
    assert r.trades == []
    n_sig = len(r.events("signal"))
    d2: list[Row] = [(25011, 25012, 25010, 25011.5)] * 3
    r.feed(d2, D2)
    (t,) = r.trades
    assert t.exit_reason == "SESSION_END" and t.exit_px == 25011.5  # first bar's close
    assert t.exit_time == CAL.session_bounds(D2)[0] + timedelta(minutes=5)
    assert len(r.events("signal")) == n_sig  # no entry while the stale inPos holds


def test_fill_price_mode_reanchors_or_declines() -> None:
    entry = 25010.5
    r = tail((entry, entry + 3, entry - 0.2, entry + 2), anchor_mode="fill_price", min_risk_atr=0.7)
    (sig,) = r.events("signal")
    assert r.events("entry")[0]["price"] == entry and sig["target"]
    # a gap far through the stop declines the fill: no trade and the day counter is released
    gap = tail(
        (sig["stop"] - 5, sig["stop"] - 4, sig["stop"] - 6, sig["stop"] - 5),
        anchor_mode="fill_price",
        min_risk_atr=0.7,
    )
    assert gap.trades == [] and gap.events("entry") == [] and gap.e.trades_today == 0


def test_volume_absent_uses_twap() -> None:
    assert "TWAP" in Run(RAMP).events("signal")[0]["why"]


def test_snapshot_restore_roundtrip() -> None:
    import json

    r = tail((25010.5, 25011, 25010, 25010.8))
    snap = json.loads(json.dumps(r.e.snapshot(), allow_nan=False))
    e2 = NvsScalper(r.p, EngineContext(INST, "5m", CAL))
    e2.restore(snap)
    assert json.dumps(e2.snapshot(), sort_keys=True) == json.dumps(snap, sort_keys=True)
    b: Bar = bar(
        CAL.session_bounds(D1)[0] + timedelta(minutes=35),
        25011,
        25012,
        25010,
        25011,
        0.0,
        tf="5m",
        volume_kind="absent",
    )
    assert e2.on_bar(b).plots == r.e.on_bar(b).plots


def test_rsi_fade_and_use_rsi_off() -> None:
    closes, prev, rows = [25000, 24999, 24998, 24997, 24996, 25000], 25000.0, []
    for c in closes:  # dip then a fresh RSI cross above 60 on the signal bar
        rows.append((prev, max(prev, c) + 0.2, min(prev, c) - 0.3, float(c)))
        prev = float(c)
    rows += [(25000, 25002, 24999.8, 25001.5), (25001.5, 25001.6, 25000.6, 25000.8)]
    drop: Row = (25000.8, 25001, 24997.0, 24997.5)
    kw: dict[str, Any] = dict(
        use_rsi=True, rsi_len=2, ema_fast_len=2, ema_slow_len=3, min_risk_atr=0.7
    )
    r = Run(rows + [drop, (24997.5, 24998, 24997, 24997.8)], **kw)
    (t,) = r.trades
    assert (t.exit_reason, t.exit_px) == ("RSI_FADE", 24997.5)  # next open after the fade bar
    assert "RSI" in r.events("signal")[0]["why"] and "crossed 60" in r.events("signal")[0]["why"]
    off = Run(rows + [drop, (24997.5, 24998, 24997, 24997.8)], **{**kw, "use_rsi": False})
    assert all(t.exit_reason != "RSI_FADE" for t in off.trades)
