from datetime import UTC, datetime, timedelta

import pytest

from nifty.contracts import Bar
from nifty.execution import BrokerEmulator

T0 = datetime(2026, 11, 2, 3, 45, tzinfo=UTC)


def mk(i: int, o: float, h: float, lo: float, c: float) -> Bar:
    t = T0 + timedelta(minutes=5 * i)
    return Bar(
        instrument_id="csv:T", provider="csv", timeframe="5m", bar_start_utc=t,
        bar_end_utc=t + timedelta(minutes=5), open=o, high=h, low=lo, close=c, volume=0,
        received_at_utc=T0,
    )  # fmt: skip


def broker(**kw: float) -> BrokerEmulator:
    return BrokerEmulator("test.eng", "csv:T", **kw)


def test_entry_fills_next_open_and_bracket_target() -> None:
    b = broker()
    assert b.on_bar(mk(0, 100, 101, 99, 100)) == []
    b.entry("long")
    b.exit(stop=95, limit=110)
    assert b.position is None  # not filled yet at the signal bar
    assert b.on_bar(mk(1, 100.5, 105, 100, 104)) == []  # filled at open 100.5, no level hit
    assert b.position == "long"
    (t,) = b.on_bar(mk(2, 104, 111, 103, 110))
    assert (t.entry_px, t.exit_px, t.exit_reason, t.gross_pts, t.bars_held) == (
        100.5,
        110,
        "TARGET",
        9.5,
        2,
    )
    assert t.exit_time == T0 + timedelta(minutes=10) and t.entry_time == T0 + timedelta(minutes=5)
    assert (t.mfe_pts, t.mae_pts) == (9.5, 0.5)  # bar1 adverse: 100.5-100 ; bar2 target 110-100.5
    assert b.position is None and b.actual_position is None


def test_bracket_can_resolve_on_the_entry_bar() -> None:
    b = broker()
    b.on_bar(mk(0, 100, 101, 99, 100))
    b.entry("short")
    b.exit(stop=103, limit=95)
    (t,) = b.on_bar(mk(1, 100, 104, 99, 103))  # opens 100, high 104 >= stop 103
    assert (t.exit_reason, t.exit_px, t.bars_held, t.side) == ("STOP", 103, 1, "short")
    assert t.gross_pts == -3


def test_gap_through_stop_fills_at_open() -> None:
    b = broker()
    b.on_bar(mk(0, 100, 100, 100, 100))
    b.entry("long")
    b.exit(stop=98)
    b.on_bar(mk(1, 100, 100, 99, 99))
    (t,) = b.on_bar(mk(2, 95, 96, 94, 95))
    assert (t.exit_px, t.exit_reason) == (95, "STOP") and "gap_through_stop" in t.flags


def test_close_fills_next_open_and_immediately_fills_current_close() -> None:
    b = broker()
    b.on_bar(mk(0, 100, 100, 100, 100))
    b.entry("long")
    b.on_bar(mk(1, 100, 102, 99, 101))
    assert b.position == "long"
    b.close("SIGNAL")  # queued
    assert b.position == "long"
    (t,) = b.on_bar(mk(2, 103, 104, 102, 103))
    assert (t.exit_px, t.exit_time, t.exit_reason) == (103, T0 + timedelta(minutes=10), "SIGNAL")
    assert b.position is None

    b2 = broker()
    b2.on_bar(mk(0, 100, 100, 100, 100))
    b2.entry("long")
    b2.on_bar(mk(1, 100, 102, 99, 101))
    t2 = b2.close(immediately=True)  # script at bar 1 closes at bar 1's close
    assert t2 is not None and (t2.exit_px, t2.exit_time) == (101, T0 + timedelta(minutes=10))
    assert b2.actual_position is None  # really flat ...
    assert b2.position == "long"  # ... but visible to the script only from t+1
    b2.on_bar(mk(2, 101, 102, 100, 101))
    assert b2.position is None


def test_close_all_immediately_and_flat_noops() -> None:
    b = broker()
    assert b.close_all(immediately=True) is None  # nothing before the first bar
    b.on_bar(mk(0, 100, 100, 100, 100))
    b.exit(stop=90)  # flat with nothing pending: ignored
    b.entry("long")
    b.on_bar(mk(1, 100, 101, 99, 100))
    t = b.close_all(immediately=True)
    assert t is not None and t.exit_px == 100 and t.bars_held == 1


def test_commission_per_side_and_qty() -> None:
    b = broker(qty=2, commission_pct=0.1)
    b.on_bar(mk(0, 100, 100, 100, 100))
    b.entry("long")
    b.exit(limit=110)
    (t,) = b.on_bar(mk(1, 100, 112, 99, 110)) or [None]  # type: ignore[list-item]
    # fill 100 in, 110 out: 0.1% of each fill value = 0.1 + 0.11 = 0.21 pts per unit
    assert t is not None and t.qty == 2
    assert t.gross_pts == 10 and t.cost_pts == pytest.approx(0.21)
    assert t.net_pts == pytest.approx(9.79)


def test_no_pyramiding_and_reversal_keeps_new_bracket() -> None:
    b = broker()
    b.on_bar(mk(0, 100, 100, 100, 100))
    b.entry("long")
    b.on_bar(mk(1, 100, 101, 99, 100))
    b.entry("long")  # same side again: ignored
    assert b.on_bar(mk(2, 100, 101, 99, 100)) == []
    b.entry("short")  # reverse, with a bracket meant for the NEW position
    b.exit(stop=105, limit=95)
    (closed,) = b.on_bar(mk(3, 100, 101, 99, 100))
    assert closed.exit_reason == "REVERSE" and closed.side == "long"
    assert b.position == "short"
    (t,) = b.on_bar(mk(4, 100, 100.5, 94, 95))
    assert (t.side, t.exit_reason, t.exit_px) == ("short", "TARGET", 95)


def test_trade_ids_are_sequential() -> None:
    b = broker()
    b.on_bar(mk(0, 100, 100, 100, 100))
    ids = []
    for i in range(1, 6, 2):
        b.entry("long")
        b.on_bar(mk(i, 100, 100, 100, 100))
        b.close()
        ids += [t.trade_id for t in b.on_bar(mk(i + 1, 100, 100, 100, 100))]
    assert ids == ["test.eng:1", "test.eng:2", "test.eng:3"]
