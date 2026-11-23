"""KiteStream against a local fake WebSocket server (no network)."""

import asyncio
import json
import struct
from http import HTTPStatus

import pytest
from websockets.asyncio.server import ServerConnection, serve

from nifty.collector.packets import FrameResult
from nifty.collector.ws import KiteStream, chunks
from nifty.marketdata.base import ProviderError

FRAME = struct.pack(">H", 1) + struct.pack(">H", 8) + struct.pack(">2i", 256265, 2521530)


async def no_sleep(_: float) -> None:
    await asyncio.sleep(0)


async def test_subscribes_receives_frames_and_reconnects_after_a_drop() -> None:
    subs: list[list[object]] = []
    conns = {"n": 0}

    async def handler(ws: ServerConnection) -> None:
        conns["n"] += 1
        subs.append([json.loads(await ws.recv()), json.loads(await ws.recv())])
        await ws.send(FRAME)
        await ws.send(b"\x00")  # heartbeat
        if conns["n"] == 1:
            await ws.close()  # drop: the client must reconnect and resubscribe
        else:
            await asyncio.sleep(0.3)

    got: list[FrameResult] = []
    status: list[str] = []
    stop = asyncio.Event()

    def on_frame(r: FrameResult) -> None:
        got.append(r)
        if sum(1 for g in got if g.ticks) >= 2:
            stop.set()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        s = KiteStream("key", "tok", [256265, 11000001], on_frame, lambda st, d: status.append(st),
                       base_url=f"ws://127.0.0.1:{port}", sleep=no_sleep)  # fmt: skip
        await asyncio.wait_for(s.run(stop), 10)
    assert subs[0] == [
        {"a": "subscribe", "v": [256265, 11000001]},
        {"a": "mode", "v": ["full", [256265, 11000001]]},
    ]
    assert subs[1] == subs[0]  # resubscribed after the reconnect
    assert s.reconnects >= 1 and status.count("connected") == 2 and "disconnected" in status
    assert any(g.heartbeat for g in got) and [t.token for g in got for t in g.ticks][0] == 256265


async def test_auth_failure_stops_without_retrying() -> None:
    hits = {"n": 0}

    def reject(connection: ServerConnection, request: object) -> object:
        hits["n"] += 1
        return connection.respond(HTTPStatus.FORBIDDEN, "no")

    status: list[tuple[str, str]] = []
    async with serve(lambda ws: None, "127.0.0.1", 0, process_request=reject) as server:  # type: ignore[arg-type,return-value]
        port = server.sockets[0].getsockname()[1]
        s = KiteStream("key", "SECRET-TOK", [1], lambda r: None, lambda st, d: status.append((st, d)),
                       base_url=f"ws://127.0.0.1:{port}", sleep=no_sleep)  # fmt: skip
        await asyncio.wait_for(s.run(asyncio.Event()), 10)
    assert hits["n"] == 1 and s.auth_expired  # exactly one attempt
    assert status[-1][0] == "auth_expired" and "SECRET-TOK" not in repr(s) + str(status)


async def test_error_text_message_with_token_means_auth_expired() -> None:
    async def handler(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.recv()
        await ws.send(json.dumps({"type": "error", "data": "Invalid token"}))
        await asyncio.sleep(2)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        s = KiteStream(
            "k", "t", [1], lambda r: None, base_url=f"ws://127.0.0.1:{port}", sleep=no_sleep
        )
        await asyncio.wait_for(s.run(asyncio.Event()), 10)
    assert s.auth_expired


def test_instrument_limits() -> None:
    assert [len(c) for c in chunks(list(range(3000)))] == [3000]
    assert [len(c) for c in chunks(list(range(7000)))] == [3000, 3000, 1000]
    with pytest.raises(ProviderError):
        chunks(list(range(9001)))
