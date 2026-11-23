"""Live WebSocket `/ws/v1/stream` (cookie auth; close 1008 without it).

Client: {"op":"subscribe","instrument":<symbol|instrument_id>,"timeframe":"1m","engines":[...],
         "cursor":<epoch s of the last bar it holds, optional>}
Server: `snapshot` first (bars with start >= cursor, status, engines), then `bar` (re-sent while
the bucket forms: clients REPLACE by `t`, so a resubscribe never duplicates), `event`, `panel`,
`status`. Updates are read from the DB by cursor; Redis only wakes the loop sooner and relays
provisional bars. With Redis down the loop simply polls every second."""

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import text

from nifty.api.auth import COOKIE
from nifty.config import get_settings
from nifty.db import chart
from nifty.db.instruments import find_instrument
from nifty.db.live import read_status, status_summary
from nifty.db.session import get_engine
from nifty.engines.base import get_engine as get_engine_spec
from nifty.security import read_session
from nifty.timeutil import Calendar

log = logging.getLogger("nifty.api.stream")
router = APIRouter()
POLL_S = 1.0
QUEUE_MAX = 200
SEND_TIMEOUT_S = 5.0
TFS = {"1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"}


class Outbox:
    """Bounded per-client queue: provisional updates are dropped first; a client that cannot drain
    even the essential messages is disconnected."""

    def __init__(self) -> None:
        self.q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(QUEUE_MAX)
        self.dropped = 0
        self.overflow = False

    def put(self, msg: dict[str, Any], droppable: bool = False) -> None:
        if self.q.full():
            if droppable:
                self.dropped += 1
                return
            self.overflow = True
            return
        self.q.put_nowait(msg)


def _bars_msg(page: chart.BarsPage, final_flags: list[bool]) -> dict[str, Any]:
    return {
        "t": page.t,
        "o": page.o,
        "h": page.h,
        "l": page.l,
        "c": page.c,
        "v": page.v,
        "final": final_flags,
    }


class Session:
    def __init__(
        self, iid: str, symbol: str, tf: str, engines: list[str], cursor: int | None
    ) -> None:
        self.iid, self.symbol, self.tf, self.engines = iid, symbol, tf, engines
        self.cursor = cursor
        self.sent: dict[int, tuple[float, ...]] = {}
        self.ev_ord: dict[str, int] = {}
        self.plot_t: dict[str, int] = {}
        self.last_status: str | None = None
        self.last_status_at = 0.0
        self.cal = Calendar.load()

    # ---- sync DB work (run in a thread) ------------------------------------------------------
    def read(self, snapshot: bool) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with get_engine().connect() as c:
            limit = 400 if snapshot and self.cursor is None else 12
            page = chart.bars_page(c, self.iid, self.tf, None, None, limit, None, self.cal)
            flags = [self._final(c, t) for t in page.t]
            bars: dict[str, list[Any]] = {k: [] for k in ("t", "o", "h", "l", "c", "v", "final")}
            for i, t in enumerate(page.t):
                if self.cursor is not None and t < self.cursor:
                    continue
                sig = (page.o[i], page.h[i], page.l[i], page.c[i], page.v[i], float(flags[i]))
                if not snapshot and self.sent.get(t) == sig:
                    continue
                self.sent[t] = sig
                for k, arr in zip("ohlcv", (page.o, page.h, page.l, page.c, page.v), strict=True):
                    bars[k].append(arr[i])
                bars["t"].append(t)
                bars["final"].append(flags[i])
            if bars["t"]:
                self.cursor = max(self.cursor or 0, max(bars["t"]))
            if snapshot:
                out.append({"type": "snapshot", "instrument_id": self.iid, "symbol": self.symbol,
                            "timeframe": self.tf, "volume_kind": page.volume_kind, "bars": bars,
                            "cursor": self.cursor})  # fmt: skip
            elif bars["t"]:
                out.append({"type": "bar", "bars": bars})
            out += self._engine_msgs(c, snapshot)
            now = time.monotonic()
            st = status_summary(read_status(c))
            key = json.dumps(st, sort_keys=True, default=str)
            if snapshot or key != self.last_status or now - self.last_status_at > 5:
                self.last_status, self.last_status_at = key, now
                out.append({"type": "status", **st})
        return out

    def _final(self, c: Any, t: int) -> bool:
        """A bucket is final once the 1m data reaches its end (or the session close)."""
        if self.tf == "1m":
            return True
        from datetime import UTC, datetime, timedelta

        from nifty.contracts import TF_MINUTES

        start = datetime.fromtimestamp(t, UTC)
        end = start + (
            timedelta(days=1) if self.tf == "1d" else timedelta(minutes=TF_MINUTES[self.tf])
        )
        end = min(end, self.cal.session_bounds(self.cal.session_date(start))[1])
        last = c.execute(
            text(
                "SELECT max(bar_start_utc) FROM bars WHERE instrument_id = :i AND timeframe = '1m'"
            ),
            {"i": self.iid},
        ).scalar()
        return bool(last is not None and last + timedelta(minutes=1) >= end)

    def _engine_msgs(self, c: Any, snapshot: bool) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for eid in self.engines:
            row = c.execute(
                text(
                    "SELECT run_id, panel FROM engine_runs WHERE engine_id = :e AND source_id = :s "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"e": eid, "s": f"live:{self.iid}"},
            ).first()
            if row is None:
                continue
            rid = row[0]
            evs = c.execute(
                text(
                    "SELECT ord, envelope FROM events WHERE run_id = :r AND ord > :o ORDER BY ord"
                ),
                {"r": rid, "o": self.ev_ord.get(eid, -1)},
            ).all()
            if evs:
                self.ev_ord[eid] = evs[-1][0]
                if not snapshot:  # the snapshot's events come from the REST outputs
                    out += [{"type": "event", "engine_id": eid, "event": e[1]} for e in evs]
            pt = c.execute(
                text("SELECT max(bar_start_utc) FROM plot_points WHERE run_id = :r"), {"r": rid}
            ).scalar()
            t = int(pt.timestamp()) if pt is not None else 0
            if snapshot or t != self.plot_t.get(eid, 0):
                self.plot_t[eid] = t
                out.append(
                    {"type": "panel", "engine_id": eid, "run_id": rid, "panel": row[1], "t": t}
                )
        return out


def resolve(symbol: str) -> str | None:
    with get_engine().connect() as c:
        ins = find_instrument(c, symbol)
    return ins.instrument_id if ins else None


@router.websocket("/ws/v1/stream")
async def stream(ws: WebSocket) -> None:
    s = get_settings()
    tok = ws.cookies.get(COOKIE)
    uid = read_session(s.app_secret_key, tok) if tok and s.app_secret_key else None
    origin = ws.headers.get("origin")
    if uid is None or (origin is not None and origin not in s.origins):
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        sub = json.loads(await asyncio.wait_for(ws.receive_text(), 10))
        tf = sub.get("timeframe", "1m")
        if sub.get("op") != "subscribe" or tf not in TFS:
            raise ValueError("expected {op: subscribe, instrument, timeframe}")
        iid = await asyncio.to_thread(resolve, str(sub.get("instrument", "")))
        if iid is None:
            raise ValueError("unknown instrument")
        engines = [e for e in sub.get("engines", []) if isinstance(e, str)]
        for e in engines:
            get_engine_spec(e)
        cur = sub.get("cursor")
        sess = Session(
            iid, str(sub["instrument"]), tf, engines, int(cur) if cur is not None else None
        )
    except (TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        await ws.close(code=1003, reason=str(e)[:100])
        return

    out = Outbox()
    for m in await asyncio.to_thread(sess.read, True):
        out.put(m)

    pubsub: Any = None
    try:
        import redis.asyncio as aredis

        r = aredis.from_url(s.redis_url, socket_connect_timeout=0.5)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"live:{iid}")
    except Exception:  # noqa: BLE001
        pubsub = None  # Redis down: poll the DB every second

    async def sender() -> None:
        while True:
            msg = await out.q.get()
            await asyncio.wait_for(ws.send_text(json.dumps(msg, default=str)), SEND_TIMEOUT_S)
            if out.overflow:
                await ws.close(code=1013, reason="slow client")
                return

    async def poller() -> None:
        while True:
            if pubsub is not None:
                try:
                    m = await pubsub.get_message(ignore_subscribe_messages=True, timeout=POLL_S)
                except Exception:  # noqa: BLE001
                    pubsub_failed()
                    m = None
                if m and m.get("type") == "message":
                    try:
                        body = json.loads(m["data"])
                    except ValueError:
                        body = {}
                    if body.get("type") == "provisional":
                        if tf != "1m":  # the forming minute is not a candle of a higher timeframe
                            continue
                        out.put(
                            {"type": "bar", "provisional": True, "bar": body["bar"]}, droppable=True
                        )
                        continue
            else:
                await asyncio.sleep(POLL_S)
            for msg in await asyncio.to_thread(sess.read, False):
                out.put(msg)
            if out.overflow:
                return

    def pubsub_failed() -> None:
        nonlocal pubsub
        pubsub = None

    async def watch_client() -> None:
        while True:
            await (
                ws.receive_text()
            )  # clients send nothing after subscribe; this notices disconnects

    tasks = [asyncio.create_task(f()) for f in (sender, poller, watch_client)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        if pubsub is not None:
            try:
                await pubsub.close()
            except Exception:  # noqa: BLE001
                pass
