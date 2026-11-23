from datetime import UTC, datetime, timedelta

from nifty.collector.bars import BarBuilder, Throttle, Watchdog
from nifty.collector.packets import PacketTick

D = datetime(2026, 11, 23, 4, 0, tzinfo=UTC)  # 09:30 IST Monday


def tk(sec: float, ltp: float, vol: float | None = None, base: datetime = D) -> PacketTick:
    return PacketTick(1, ltp, exchange_ts=base + timedelta(seconds=sec), volume=vol)


def test_rollover_finalizes_from_tick_time_not_wall_clock() -> None:
    b = BarBuilder("kite:T", is_index=True)
    assert (
        b.on_tick(tk(1, 100)) == []
        and b.on_tick(tk(30, 103)) == []
        and b.on_tick(tk(59, 101)) == []
    )
    done = b.on_tick(tk(61, 102))  # first tick of the next minute finalizes the previous one
    assert len(done) == 1
    bar = done[0]
    assert (bar.open, bar.high, bar.low, bar.close) == (100, 103, 100, 101) and bar.finalized
    assert bar.bar_start_utc == D and bar.bar_end_utc == D + timedelta(minutes=1)
    assert (
        bar.volume_kind == "absent" and "volume_absent" in bar.quality_flags and bar.volume == 0.0
    )
    prov = b.provisional()
    assert prov is not None and not prov.finalized and prov.open == 102


def test_out_of_order_and_duplicates_and_late_ticks() -> None:
    b = BarBuilder("kite:T", is_index=True)
    for s, p in [
        (10, 100),
        (30, 105),
        (20, 98),
        (30, 105),
        (30, 105),
    ]:  # 20 is out of order; 30 duplicated
        b.on_tick(tk(s, p))
    (bar,) = b.on_tick(tk(65, 101))
    assert (bar.open, bar.high, bar.low, bar.close) == (
        100,
        105,
        98,
        105,
    )  # close = latest by timestamp
    assert b.dup_ticks == 2
    assert (
        b.on_tick(tk(40, 999)) == [] and b.late_ticks == 1
    )  # minute already final: never rewritten
    assert b.provisional() is not None and b.provisional().open == 101  # type: ignore[union-attr]


def test_volume_is_delta_of_cumulative_and_resets_on_a_new_day() -> None:
    b = BarBuilder("kite:F", is_index=False)
    b.on_tick(tk(1, 100, 1000))
    (b1,) = b.on_tick(tk(61, 101, 1300))
    assert b1.volume == 1000.0 and b1.volume_kind == "exchange"  # day's first bar: from 0
    b.on_tick(tk(100, 102, 1500))
    (b2,) = b.on_tick(tk(121, 103, 1600))
    assert b2.volume == 500.0  # 1500 at the end of minute 2 minus 1000 at the end of minute 1
    nxt = D + timedelta(days=1)  # Tuesday: cumulative restarts
    b.on_tick(tk(1, 100, 50, nxt))
    (b3,) = b.on_tick(tk(61, 100, 80, nxt))
    assert b3.volume == 50.0 and b3.bar_start_utc == nxt  # not 50 - 1600


def test_off_session_ticks_are_ignored() -> None:
    b = BarBuilder("kite:T", is_index=True)
    pre = datetime(2026, 11, 23, 3, 0, tzinfo=UTC)  # 08:30 IST
    sat = datetime(2026, 11, 21, 5, 0, tzinfo=UTC)
    assert b.on_tick(tk(0, 100, base=pre)) == [] and b.on_tick(tk(0, 100, base=sat)) == []
    assert b.dropped_offsession == 2 and b.provisional() is None


def test_received_time_fallback_and_flush() -> None:
    b = BarBuilder("kite:T", is_index=True)
    assert b.on_tick(PacketTick(1, 100.0)) == []  # no exchange ts and no received time: ignored
    b.on_tick(PacketTick(1, 100.0), received=D)
    f = b.flush()
    assert f is not None and f.finalized and b.flush() is None


def test_throttle_and_watchdog_use_injected_clock() -> None:
    t = Throttle(0.25)
    assert [t.ok(x) for x in (0.0, 0.1, 0.24, 0.25, 0.3, 0.5)] == [
        True,
        False,
        False,
        True,
        False,
        True,
    ]
    w = Watchdog(15)
    assert not w.stale(100) and w.age(100) is None  # nothing seen yet is not "stale"
    w.beat(100)
    assert not w.stale(114) and w.stale(116) and w.age(116) == 16
