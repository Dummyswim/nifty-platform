"""Kite binary WebSocket packets (pure). Layouts and sizes: docs/spec/08-kite-verified.md.

Frame = int16 packet count, then per packet an int16 length and the packet; 1 byte = heartbeat.
Packet sizes: 8 ltp, 44 quote, 184 full (tradable); 28 quote / 32 full (index). Fields are
big-endian int32 (endianness is not documented: assumed, see spec/08); prices are paise (/100).
"""

import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nifty.marketdata.base import ErrorCode, ProviderError

PRICE_DIV = 100.0
CURRENCY_DIV = 10_000_000.0  # currency segments only; not used for NSE/NFO


@dataclass(frozen=True)
class PacketTick:
    token: int
    ltp: float
    exchange_ts: datetime | None = None  # absent in ltp/quote packets
    last_ts: datetime | None = None
    volume: float | None = None  # day's cumulative traded volume (None for the index)
    oi: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_qty: float | None = None
    ask_qty: float | None = None
    is_index: bool = False
    size: int = 0


@dataclass
class FrameResult:
    ticks: list[PacketTick] = field(default_factory=list)
    heartbeat: bool = False
    errors: list[str] = field(default_factory=list)  # malformed packets: skipped, never fatal


def _ts(sec: int) -> datetime | None:
    return datetime.fromtimestamp(sec, UTC) if sec > 0 else None


def split_frame(data: bytes) -> list[bytes]:
    """Packets of one binary message. A 1-byte message is a heartbeat (no packets)."""
    if len(data) <= 1:
        return []
    if len(data) < 2:
        raise ProviderError(ErrorCode.BAD_DATA, "frame too short")
    (n,) = struct.unpack_from(">H", data, 0)
    pos, out = 2, []
    for i in range(n):
        if pos + 2 > len(data):
            raise ProviderError(ErrorCode.BAD_DATA, f"frame truncated before packet {i}")
        (ln,) = struct.unpack_from(">H", data, pos)
        pos += 2
        if ln == 0 or pos + ln > len(data):
            raise ProviderError(ErrorCode.BAD_DATA, f"packet {i} length {ln} overruns the frame")
        out.append(data[pos : pos + ln])
        pos += ln
    return out


def parse_packet(p: bytes, div: float = PRICE_DIV) -> PacketTick:
    n = len(p)
    if n not in (8, 28, 32, 44, 184):
        raise ProviderError(ErrorCode.BAD_DATA, f"unknown packet size {n}")

    def i32(off: int) -> int:
        return int(struct.unpack_from(">i", p, off)[0])

    token, ltp = i32(0), i32(4) / div
    if n == 8:
        return PacketTick(token, ltp, size=n)
    if n in (28, 32):  # index: token ltp high low open close change [exchange_ts]
        return PacketTick(
            token, ltp, exchange_ts=_ts(i32(28)) if n == 32 else None, is_index=True, size=n
        )
    volume = float(i32(16))
    if n == 44:
        return PacketTick(token, ltp, volume=volume, size=n)
    depth = _depth(p, div)
    return PacketTick(
        token, ltp, exchange_ts=_ts(i32(60)), last_ts=_ts(i32(44)), volume=volume,
        oi=float(i32(48)), bid=depth[0], ask=depth[2], bid_qty=depth[1], ask_qty=depth[3], size=n,
    )  # fmt: skip


Quad = tuple[float | None, float | None, float | None, float | None]


def _depth(p: bytes, div: float) -> Quad:
    """Best bid price/qty and ask price/qty (entry: qty int32, price int32, orders int16, pad)."""
    bq, bp = struct.unpack_from(">ii", p, 64)
    aq, ap = struct.unpack_from(">ii", p, 124)
    return (
        bp / div if bp else None,
        float(bq) if bp else None,
        ap / div if ap else None,
        float(aq) if ap else None,
    )


def parse_frame(data: bytes, div: float = PRICE_DIV) -> FrameResult:
    """Never raises: malformed frames/packets are reported in `errors` and skipped."""
    res = FrameResult(heartbeat=len(data) == 1)
    try:
        packets = split_frame(data)
    except ProviderError as e:
        res.errors.append(str(e))
        return res
    for pk in packets:
        try:
            res.ticks.append(parse_packet(pk, div))
        except ProviderError as e:
            res.errors.append(str(e))
    return res
