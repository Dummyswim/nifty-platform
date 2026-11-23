"""Packets built with struct.pack from the documented offsets (spec/08), independent of the parser."""

import struct
from datetime import UTC, datetime

import pytest

from nifty.collector.packets import PacketTick, parse_frame, parse_packet, split_frame
from nifty.marketdata.base import ProviderError

TS = int(datetime(2026, 11, 23, 4, 0, 5, tzinfo=UTC).timestamp())  # 09:30:05 IST


def index_packet(full: bool = True) -> bytes:
    # 0 token, 4 ltp, 8 high, 12 low, 16 open, 20 close, 24 change, 28 exchange ts
    b = struct.pack(">6i", 256265, 2521530, 2522000, 2519000, 2520000, 2518000) + struct.pack(
        ">i", 3530
    )
    return b + (struct.pack(">i", TS) if full else b"")


def full_packet() -> bytes:
    head = struct.pack(">i", 11000001) + struct.pack(">i", 2525000)  # token, ltp
    head += struct.pack(">i", 75) + struct.pack(">i", 2524000)  # last qty, avg price
    head += (
        struct.pack(">i", 123456) + struct.pack(">i", 1000) + struct.pack(">i", 900)
    )  # volume, buy qty, sell qty
    head += struct.pack(">4i", 2520000, 2530000, 2510000, 2515000)  # o h l c
    head += (
        struct.pack(">i", TS - 1) + struct.pack(">i", 7777) + struct.pack(">2i", 8000, 7000)
    )  # last ts, oi, oi hi, oi lo
    head += struct.pack(">i", TS)  # exchange ts at 60
    assert len(head) == 64

    def entry(q: int, p: int) -> bytes:
        return struct.pack(">iih", q, p, 3) + b"\x00\x00"

    bids = entry(50, 2524950) + entry(40, 2524900) + b"".join(entry(0, 0) for _ in range(3))
    asks = entry(60, 2525050) + entry(30, 2525100) + b"".join(entry(0, 0) for _ in range(3))
    return head + bids + asks


def frame(*packets: bytes) -> bytes:
    return struct.pack(">H", len(packets)) + b"".join(
        struct.pack(">H", len(p)) + p for p in packets
    )


def test_index_full_and_quote() -> None:
    t = parse_packet(index_packet())
    assert (t.token, t.ltp, t.is_index, t.size) == (256265, 25215.30, True, 32)
    assert t.exchange_ts == datetime.fromtimestamp(TS, UTC) and t.volume is None
    q = parse_packet(index_packet(full=False))
    assert q.size == 28 and q.exchange_ts is None and q.ltp == 25215.30


def test_ltp_and_quote_tradable() -> None:
    assert parse_packet(struct.pack(">2i", 11000001, 2525075)) == PacketTick(
        11000001, 25250.75, size=8
    )
    quote = (
        struct.pack(">i", 11000001)
        + struct.pack(">i", 2525000)
        + struct.pack(">i", 75)
        + struct.pack(">i", 2524000)
    )
    quote += struct.pack(">i", 5000) + struct.pack(">2i", 10, 20) + struct.pack(">4i", 1, 2, 3, 4)
    t = parse_packet(quote)
    assert (t.volume, t.exchange_ts, t.size) == (5000.0, None, 44)


def test_full_tradable_fields_and_depth() -> None:
    t = parse_packet(full_packet())
    assert (t.token, t.ltp, t.volume, t.oi) == (11000001, 25250.0, 123456.0, 7777.0)
    assert t.exchange_ts == datetime.fromtimestamp(TS, UTC) and t.last_ts == datetime.fromtimestamp(
        TS - 1, UTC
    )
    assert (t.bid, t.bid_qty, t.ask, t.ask_qty) == (25249.50, 50.0, 25250.50, 60.0)
    assert not t.is_index and t.size == 184


def test_frame_with_two_packets_and_heartbeat() -> None:
    res = parse_frame(frame(index_packet(), full_packet()))
    assert (
        [t.token for t in res.ticks] == [256265, 11000001] and not res.errors and not res.heartbeat
    )
    hb = parse_frame(b"\x00")
    assert hb.heartbeat and hb.ticks == [] and hb.errors == []
    assert split_frame(b"\x00") == []


def test_malformed_never_crashes_and_is_reported() -> None:
    bad_size = frame(b"\x00" * 13)
    r = parse_frame(bad_size)
    assert r.ticks == [] and "unknown packet size 13" in r.errors[0]
    r2 = parse_frame(frame(index_packet(), b"\x00" * 9))  # one good, one bad: the good one survives
    assert len(r2.ticks) == 1 and len(r2.errors) == 1
    assert parse_frame(struct.pack(">H", 3) + struct.pack(">H", 8)).errors  # truncated
    assert parse_frame(struct.pack(">HH", 1, 500) + b"\x00" * 10).errors  # length overruns
    with pytest.raises(ProviderError):
        parse_packet(b"\x00\x01")
    for junk in (b"", b"\xff\xff\xff", bytes(range(50))):
        parse_frame(junk)  # no exception


def test_currency_divisor_is_a_parameter() -> None:
    t = parse_packet(struct.pack(">2i", 1, 835_000_000), div=10_000_000.0)
    assert t.ltp == pytest.approx(83.5)
