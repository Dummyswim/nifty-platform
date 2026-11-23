"""Kite WebSocket client (read-only market data). Credentials ride in the URL query, so the URL is
never logged or shown in a repr. <= 3000 instruments per connection, <= 3 connections (spec/08)."""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from nifty.collector.packets import FrameResult, parse_frame
from nifty.marketdata.base import ErrorCode, ProviderError

log = logging.getLogger("nifty.collector.ws")
MAX_PER_CONN, MAX_CONNS = 3000, 3
BASE_URL = "wss://ws.kite.trade"

OnFrame = Callable[[FrameResult], Awaitable[None] | None]
OnStatus = Callable[[str, str], Awaitable[None] | None]  # (state, detail)


def chunks(tokens: list[int]) -> list[list[int]]:
    parts = [tokens[i : i + MAX_PER_CONN] for i in range(0, len(tokens), MAX_PER_CONN)]
    if len(parts) > MAX_CONNS:
        raise ProviderError(
            ErrorCode.BAD_DATA, f"{len(tokens)} instruments exceed {MAX_PER_CONN * MAX_CONNS}"
        )
    return parts


class KiteStream:
    def __init__(
        self,
        api_key: str,
        access_token: str,
        tokens: list[int],
        on_frame: OnFrame,
        on_status: OnStatus | None = None,
        *,
        base_url: str = BASE_URL,
        mode: str = "full",
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_backoff: float = 30.0,
    ) -> None:
        self._url = f"{base_url}?api_key={api_key}&access_token={access_token}"
        self._parts = chunks(tokens)
        self.on_frame, self.on_status, self.mode = on_frame, on_status, mode
        self._sleep, self.max_backoff = sleep, max_backoff
        self.reconnects = 0
        self.auth_expired = False

    def __repr__(self) -> str:
        return f"KiteStream(instruments={sum(map(len, self._parts))}, mode={self.mode})"

    async def _emit(self, state: str, detail: str = "") -> None:
        if self.on_status:
            r = self.on_status(state, detail)
            if asyncio.iscoroutine(r):
                await r

    async def _deliver(self, res: FrameResult) -> None:
        r = self.on_frame(res)
        if asyncio.iscoroutine(r):
            await r

    async def _one(self, tokens: list[int], stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set() and not self.auth_expired:
            try:
                async with websockets.connect(self._url, max_size=2**22, open_timeout=15) as ws:
                    await ws.send(json.dumps({"a": "subscribe", "v": tokens}))
                    await ws.send(json.dumps({"a": "mode", "v": [self.mode, tokens]}))
                    backoff = 1.0
                    await self._emit("connected")
                    async for msg in ws:
                        if stop.is_set():
                            return
                        if isinstance(msg, bytes):
                            await self._deliver(parse_frame(msg))
                        elif self._text_means_auth_error(msg):
                            self.auth_expired = True
                            await self._emit("auth_expired", "token rejected")
                            return
                await self._emit("disconnected", "closed by server")
            except InvalidStatus as e:
                if e.response.status_code in (401, 403):
                    self.auth_expired = True
                    await self._emit(
                        "auth_expired", f"handshake rejected ({e.response.status_code})"
                    )
                    return  # no retry storm: the user must reconnect Kite
                await self._emit("disconnected", f"handshake status {e.response.status_code}")
            except (ConnectionClosed, WebSocketException, OSError, TimeoutError) as e:
                await self._emit("disconnected", type(e).__name__)
            if stop.is_set() or self.auth_expired:
                return
            self.reconnects += 1
            await self._sleep(backoff + random.random() * backoff / 2)
            backoff = min(backoff * 2, self.max_backoff)

    @staticmethod
    def _text_means_auth_error(msg: str) -> bool:
        try:
            d: Any = json.loads(msg)
        except ValueError:
            return False
        return (
            isinstance(d, dict)
            and d.get("type") == "error"
            and "token" in str(d.get("data", "")).lower()
        )

    async def run(self, stop: asyncio.Event) -> None:
        await asyncio.gather(*(self._one(p, stop) for p in self._parts))
