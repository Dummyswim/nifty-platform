"""Live pipeline: ticks -> 1m bars -> engines -> DB (one transaction) -> Redis (best effort).

`Pipeline` is shared by the Kite collector (`python -m nifty.collector`) and `demo-replay`.
Order per finalized bar: DB first (bar + engine outputs commit together), then Redis. The API
serves clients from the DB (cursor polling) and uses Redis only as a wake-up and for provisional
bars, so a Redis outage degrades latency, never correctness."""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text

from nifty.collector.bars import BarBuilder, Throttle, Watchdog
from nifty.collector.packets import PacketTick
from nifty.contracts import Bar, Instrument
from nifty.db.bars import read_bars, upsert_bars
from nifty.db.live import append_delta, ensure_live_run, insert_ticks, write_status
from nifty.engines.base import get_engine, load_builtin_engines
from nifty.engines.live import LiveRun, live_timeframes, run_label
from nifty.timeutil import Calendar, utcnow

log = logging.getLogger("nifty.collector")
WARMUP_SESSIONS = 5
STALE_AFTER_S = 15.0


class Publisher:
    """Redis pub/sub, best effort: any failure is swallowed (the DB is the source of truth)."""

    def __init__(self, url: str | None) -> None:
        self._r: Any = None
        self.ok = False
        if url:
            try:
                import redis

                self._r = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
                self._r.ping()
                self.ok = True
            except Exception:  # noqa: BLE001
                log.warning("redis unavailable: live updates fall back to DB polling")

    def publish(self, channel: str, msg: dict[str, Any]) -> None:
        if self._r is None:
            return
        try:
            self._r.publish(channel, json.dumps(msg, default=str))
            self.ok = True
        except Exception:  # noqa: BLE001
            self.ok = False


def bar_json(b: Bar) -> dict[str, Any]:
    return {"t": int(b.bar_start_utc.timestamp()), "o": b.open, "h": b.high, "l": b.low,
            "c": b.close, "v": b.volume, "final": b.finalized}  # fmt: skip


@dataclass
class Feed:
    instrument: Instrument
    builder: BarBuilder
    runs: list[LiveRun] = field(default_factory=list)
    run_ids: dict[str, str] = field(default_factory=dict)
    default_tf: dict[str, bool] = field(
        default_factory=dict
    )  # run label -> is the engine default tf


class Pipeline:
    def __init__(
        self,
        db: Engine,
        publisher: Publisher | None = None,
        calendar: Calendar | None = None,
        clock: Callable[[], float] = time.monotonic,
        provider: str = "kite",
    ) -> None:
        self.db, self.pub = db, publisher or Publisher(None)
        self.cal = calendar or Calendar.load()
        self.clock, self.provider = clock, provider
        self.feeds: dict[str, Feed] = {}
        self.watchdog, self.throttle = Watchdog(STALE_AFTER_S), Throttle(0.25)
        self._ticks: list[tuple[str, PacketTick, datetime]] = []
        self._last_flush = clock()
        self.state: dict[str, Any] = {"connected": False, "auth_expired": False, "reconnects": 0,
                                      "bad_packets": 0, "detail": ""}  # fmt: skip
        self.n_ticks = 0

    # ---- setup ---------------------------------------------------------------------------------
    def add_feed(self, ins: Instrument, engines: dict[str, dict[str, Any]] | None = None) -> Feed:
        """`engines` = {engine_id: params}; each gets a LiveRun rebuilt by replaying stored bars."""
        load_builtin_engines()
        is_index = ins.instrument_type == "INDEX"
        feed = Feed(ins, BarBuilder(ins.instrument_id, is_index, self.cal, self.provider))
        for eid, params in (engines or {}).items():
            spec = get_engine(eid)  # unknown / unready engine: fail at startup, not mid-session
            for tf in live_timeframes(eid, spec.cls.default_timeframe):
                feed.runs.append(LiveRun(eid, params, ins, tf, self.cal))
                feed.default_tf[run_label(eid, tf)] = tf == spec.cls.default_timeframe
        self.feeds[ins.instrument_id] = feed
        self.rebuild_runs(feed)
        return feed

    def rebuild_runs(self, feed: Feed) -> None:
        """Restart/resync (D14): fresh runners replay the stored 1m bars of the last sessions; the
        outputs are written again idempotently, so the result equals an uninterrupted run."""
        if not feed.runs:
            return
        with self.db.begin() as c:
            last = c.execute(
                text(
                    "SELECT max(bar_start_utc) FROM bars "
                    "WHERE instrument_id = :i AND timeframe = '1m'"
                ),
                {"i": feed.instrument.instrument_id},
            ).scalar()
            bars: list[Bar] = []
            if last is not None:
                first_day = self.cal.session_date(last)
                for _ in range(WARMUP_SESSIONS - 1):
                    first_day -= timedelta(days=1)
                    while not self.cal.is_session_day(first_day):
                        first_day -= timedelta(days=1)
                bars = read_bars(
                    c, feed.instrument.instrument_id, "1m", self.cal.session_bounds(first_day)[0]
                )
            fresh = [
                LiveRun(r.engine_id, r.params, feed.instrument, r.timeframe, self.cal)
                for r in feed.runs
            ]
            for run in fresh:
                rid = ensure_live_run(c, run, feed.instrument.instrument_id)
                feed.run_ids[run_label(run.engine_id, run.timeframe)] = rid
                for b in bars:
                    append_delta(c, rid, run.feed(b))
            feed.runs = fresh
        log.info(
            "engines rebuilt for %s from %d stored 1m bars",
            feed.instrument.instrument_id,
            len(bars),
        )

    # ---- hot path ------------------------------------------------------------------------------
    def handle_tick(
        self, instrument_id: str, tick: PacketTick, received: datetime | None = None
    ) -> None:
        now = self.clock()
        recv = received or utcnow()
        self.watchdog.beat(now)
        self.n_ticks += 1
        feed = self.feeds[instrument_id]
        self._ticks.append((instrument_id, tick, recv))
        for bar in feed.builder.on_tick(tick, recv):
            self.process_bar(feed, bar)
        if self.throttle.ok(now):
            prov = feed.builder.provisional()
            if prov is not None:
                msg: dict[str, Any] = {"type": "provisional", "bar": bar_json(prov)}
                for run in feed.runs:
                    if not feed.default_tf[run_label(run.engine_id, run.timeframe)]:
                        continue  # early alerts come from the default-timeframe run only
                    p = run.provisional(prov)
                    if p is not None:
                        evs = [e.model_dump(mode="json") for e in p["events"]]
                        msg.setdefault("engines", {})[run.engine_id] = {
                            "plots": p["plots"],
                            "events": evs,
                        }
                self.pub.publish(f"live:{instrument_id}", msg)
        if len(self._ticks) >= 500 or now - self._last_flush >= 1.0:
            self.flush_ticks()

    def process_bar(self, feed: Feed, bar: Bar) -> None:
        """DB first (bar + engine outputs in one transaction), then Redis."""
        deltas = []
        with self.db.begin() as c:
            upsert_bars(c, [bar])
            for run in feed.runs:
                d = run.feed(bar)
                append_delta(c, feed.run_ids[run_label(run.engine_id, run.timeframe)], d)
                deltas.append(d)
        self.pub.publish(
            f"live:{feed.instrument.instrument_id}", {"type": "wake", "bar": bar_json(bar)}
        )

    def flush_ticks(self) -> None:
        rows, self._ticks, self._last_flush = self._ticks, [], self.clock()
        if rows:
            with self.db.begin() as c:
                insert_ticks(c, rows)

    # ---- status --------------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        now = self.clock()
        age = self.watchdog.age(now)
        return {
            **self.state, "provider": self.provider, "stale": self.watchdog.stale(now),
            "last_tick_age_s": None if age is None else round(age, 1),
            "instruments": sorted(self.feeds), "ticks": self.n_ticks,
            "late_ticks": sum(f.builder.late_ticks for f in self.feeds.values()),
            "redis": self.pub.ok,
        }  # fmt: skip

    def write_status(self) -> None:
        s = self.status()
        with self.db.begin() as c:
            write_status(c, s)
        self.pub.publish("live:status", s)

    def finish(self) -> None:
        for feed in self.feeds.values():
            b = feed.builder.flush()
            if b is not None:
                self.process_bar(feed, b)
        self.flush_ticks()
