"""`python -m nifty.collector`: Kite live collector (needs a stored token and market hours)."""

import asyncio
import logging
import signal
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from nifty.collector.packets import FrameResult
from nifty.collector.reconcile import plan_reconcile
from nifty.collector.service import Pipeline, Publisher
from nifty.collector.ws import KiteStream
from nifty.config import Settings, get_settings
from nifty.contracts import Instrument
from nifty.db.bars import read_bars, upsert_bars
from nifty.db.instruments import option_instruments
from nifty.db.kite import kite_instruments, load_token
from nifty.db.session import get_engine
from nifty.marketdata.base import ProviderError
from nifty.marketdata.kite.client import KiteClient
from nifty.marketdata.kite.master import front_month_future, nifty_index
from nifty.marketdata.kite.provider import KiteProvider
from nifty.marketdata.validation import validate_bars
from nifty.options.bs import effective_today
from nifty.options.chain import EXPIRY_KINDS, expiry_kinds
from nifty.options.window import WindowPlanner
from nifty.timeutil import IST, Calendar, utcnow

log = logging.getLogger("nifty.collector")
RECONCILE_AFTER = (15, 35)  # IST
VIX_SYMBOL = "INDIA VIX"


def vix_index(ins: list[Instrument]) -> Instrument | None:
    return next(
        (
            i
            for i in ins
            if i.instrument_type == "INDEX"
            and i.exchange == "NSE"
            and i.tradingsymbol == VIX_SYMBOL
            and i.provider_token is not None
        ),
        None,
    )


def enabled_engines(prefs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Engines the UI has switched on (NVS by default) with their saved params."""
    saved = prefs.get("indicators") or {}
    ids = {k for k, v in saved.items() if isinstance(v, dict) and v.get("enabled")}
    if "pine.nvs_scalper" not in saved:
        ids.add("pine.nvs_scalper")
    return {i: dict((saved.get(i) or {}).get("params") or {}) for i in sorted(ids)}


def make_planner(
    prefs: dict[str, Any], options: list[Instrument], now: datetime
) -> WindowPlanner | None:
    """ATM +- `options.window_steps` (default 5), CE and PE, for the expiry kinds in
    `options.record_kinds` (default all three); `options.record = false` turns recording off."""
    if prefs.get("options.record", True) is False or not options:
        return None
    kinds = prefs.get("options.record_kinds") or list(EXPIRY_KINDS)
    listed = expiry_kinds([o.expiry for o in options if o.expiry], effective_today(now))
    exps = sorted({d for k in kinds if (d := listed.get(k)) is not None})
    if not exps:
        return None
    return WindowPlanner(options, exps, int(prefs.get("options.window_steps", 5)))


def backfill_gap(pipe: Pipeline, client: KiteClient, ins: Instrument, cal: Calendar) -> int:
    """Fill [last stored 1m bar + 1m, now) from Kite historical (1m only), rebuild engines."""
    now = utcnow()
    day = cal.session_date(now)
    if not cal.is_session_day(day):
        return 0
    lo, hi = cal.session_bounds(day)
    with pipe.db.connect() as c:
        have = read_bars(c, ins.instrument_id, "1m", lo, hi, last_n=1)
    start = have[-1].bar_start_utc + timedelta(minutes=1) if have else lo
    end = min(now, hi)
    if start >= end:
        return 0
    bars = list(KiteProvider(client).historical(ins, "1m", start, end))
    ok, _ = validate_bars(bars, cal)
    with pipe.db.begin() as c:
        upsert_bars(c, ok)
    if pipe.feeds.get(ins.instrument_id):
        pipe.rebuild_runs(pipe.feeds[ins.instrument_id])
    return len(ok)


def reconcile_day(pipe: Pipeline, client: KiteClient, ins: Instrument, cal: Calendar) -> int:
    day = cal.session_date(utcnow())
    lo, hi = cal.session_bounds(day)
    fetched = list(KiteProvider(client).historical(ins, "1m", lo, hi))
    ok, _ = validate_bars(fetched, cal)
    with pipe.db.begin() as c:
        stored = read_bars(c, ins.instrument_id, "1m", lo, hi)
        changes = plan_reconcile(stored, ok)
        if changes:
            upsert_bars(c, changes)
    return len(changes)


async def run(settings: Settings | None = None) -> int:
    s = settings or get_settings()
    db = get_engine()
    with db.connect() as c:
        token = load_token(c, s.app_secret_key)
        ins = kite_instruments(c)
        option_list = option_instruments(c)
        prefs = {
            r[0]: r[1] for r in c.execute(text("SELECT key, value FROM prefs WHERE user_id = 1"))
        }
    if not (s.kite_api_key and token):
        print("Kite is not connected: Settings -> Connect Kite, then start the collector again.")
        return 2
    idx, fut = nifty_index(ins), front_month_future(ins, utcnow().date())
    vix = vix_index(ins)
    if vix is None:
        log.warning("INDIA VIX not in master; recording without it")
    if idx is None or idx.provider_token is None:
        print("instrument master missing NIFTY 50: Settings -> Refresh instruments.")
        return 2
    cal = Calendar.load()
    pipe = Pipeline(db, Publisher(s.redis_url), cal, provider="kite")
    pipe.add_feed(idx, enabled_engines(prefs))
    tokens = {idx.provider_token: idx.instrument_id}
    if fut is not None and fut.provider_token is not None:
        pipe.add_feed(fut)  # front-month future: proxy volume for the index (D10/D20)
        tokens[fut.provider_token] = fut.instrument_id
    if vix is not None and vix.provider_token is not None:
        pipe.add_feed(vix)  # India VIX: 1m bars only, no engines
        tokens[vix.provider_token] = vix.instrument_id
    client = KiteClient(s.kite_api_key, s.kite_api_secret, token)
    planner = make_planner(prefs, option_list, utcnow())
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)

    async def apply_window(add: list[Instrument], remove: list[Instrument]) -> None:
        for o in add:
            if o.instrument_id not in pipe.feeds and o.provider_token is not None:
                pipe.add_feed(o)  # option 1m bars from ticks; no engines
            if o.provider_token is not None:
                tokens[o.provider_token] = o.instrument_id
        try:
            await stream.update(
                [o.provider_token for o in add if o.provider_token is not None],
                [o.provider_token for o in remove if o.provider_token is not None],
            )
        except ProviderError as e:
            log.warning("option window update failed: %s", e)
        for o in remove:  # unsubscribed: keep the recorded data, stop mapping ticks
            tokens.pop(o.provider_token or -1, None)
        log.info("option window: +%d -%d contracts", len(add), len(remove))

    def on_frame(res: FrameResult) -> None:
        if res.heartbeat:
            pipe.watchdog.beat(pipe.clock())
        pipe.state["bad_packets"] += len(res.errors)
        for t in res.ticks:
            iid = tokens.get(t.token)
            if iid is not None:
                pipe.handle_tick(iid, t)
                if planner is not None and iid == idx.instrument_id:
                    delta = planner.update(t.ltp)  # re-centre when the ATM strike moves
                    if delta is not None:
                        asyncio.get_running_loop().create_task(apply_window(*delta))

    async def on_status(state: str, detail: str) -> None:
        pipe.state.update(connected=state == "connected", detail=detail)
        if state == "auth_expired":
            pipe.state["auth_expired"] = True
            stop.set()
        if state == "connected":
            # (re)connect: fill the gap from historical 1m, rebuild engines
            for i in (idx, fut, vix):
                if i is not None:
                    try:
                        n = await asyncio.to_thread(backfill_gap, pipe, client, i, cal)
                        log.info("backfilled %d bars for %s", n, i.instrument_id)
                    except ProviderError as e:
                        log.warning("backfill failed: %s", e)
        pipe.write_status()

    stream = KiteStream(s.kite_api_key, token, list(tokens), on_frame, on_status)
    reconciled_day = None

    async def ticker() -> None:
        nonlocal reconciled_day
        while not stop.is_set():
            pipe.state["reconnects"] = stream.reconnects
            await asyncio.to_thread(pipe.write_status)
            local: datetime = utcnow().astimezone(IST)
            if (local.hour, local.minute) >= RECONCILE_AFTER and reconciled_day != local.date():
                reconciled_day = local.date()
                for i in (idx, fut, vix):
                    if i is not None:
                        try:
                            n = await asyncio.to_thread(reconcile_day, pipe, client, i, cal)
                            log.info("EOD reconcile %s: %d revised bars", i.instrument_id, n)
                        except ProviderError as e:
                            log.warning("reconcile failed: %s", e)
            try:
                await asyncio.wait_for(stop.wait(), 2.0)
            except TimeoutError:
                pass

    log.info("collector started: %s", sorted(tokens.values()))
    await asyncio.gather(stream.run(stop), ticker())
    pipe.finish()
    pipe.write_status()
    return 3 if pipe.state["auth_expired"] else 0
