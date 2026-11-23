"""`demo-replay`: replay the oracle sessions as ticks through the live pipeline under the
instrument `demo:NIFTY 50` (never mixed with Kite data). No network, no Kite."""

import logging
import signal
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

from nifty.collector.packets import PacketTick
from nifty.collector.service import Pipeline, Publisher
from nifty.config import get_settings
from nifty.contracts import Bar, Instrument
from nifty.db.instruments import upsert_instrument
from nifty.db.session import get_engine
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from nifty.timeutil import Calendar

log = logging.getLogger("nifty.demo")
DEMO_ID = "demo:NIFTY 50"
ORACLE = Path(__file__).resolve().parents[4] / "reference" / "oracle" / "data" / "nifty_1m.csv"
TICK_GAP_S = 15


def ticks_of(bar: Bar) -> Iterator[PacketTick]:
    """Four ticks per minute (O, then H/L in the bar's likely order, then C), 15 s apart."""
    up = bar.close >= bar.open
    path = (
        [bar.open, bar.low, bar.high, bar.close] if up else [bar.open, bar.high, bar.low, bar.close]
    )
    for k, px in enumerate(path):
        yield PacketTick(
            0, px, exchange_ts=bar.bar_start_utc + timedelta(seconds=k * TICK_GAP_S), is_index=True
        )


class _Stop(Exception):
    pass


def run_demo(
    speed: float = 200.0,
    max_sessions: int | None = None,
    from_date: str | None = None,
    hold: bool = True,
) -> int:
    from nifty.engines.base import load_builtin_engines

    load_builtin_engines()
    cal = Calendar.load()
    src, _ = validate_bars(parse_csv(ORACLE, instrument_id=DEMO_ID), cal)
    if from_date:
        src = [b for b in src if cal.session_date(b.bar_start_utc).isoformat() >= from_date]
    if max_sessions:
        keep = sorted({cal.session_date(b.bar_start_utc) for b in src})[:max_sessions]
        src = [b for b in src if cal.session_date(b.bar_start_utc) in keep]
    ins = Instrument(instrument_id=DEMO_ID, provider="csv", tradingsymbol=DEMO_ID, tick_size=0.05)
    db = get_engine()
    with db.begin() as c:
        upsert_instrument(c, ins)
    pipe = Pipeline(db, Publisher(get_settings().redis_url), cal, provider="csv")
    pipe.state["connected"] = True
    pipe.state["detail"] = f"demo replay x{speed:g}"
    pipe.add_feed(ins, {"pine.nvs_scalper": {}})
    pipe.write_status()
    log.info("demo: %d bars at x%g", len(src), speed)

    def on_term(*_: object) -> None:
        raise _Stop

    signal.signal(signal.SIGTERM, on_term)
    last_status = time.monotonic()
    pause = TICK_GAP_S / speed
    try:
        for bar in src:
            for t in ticks_of(bar):
                pipe.handle_tick(DEMO_ID, t)
                time.sleep(pause)
                if time.monotonic() - last_status > 1.0:
                    pipe.write_status()
                    last_status = time.monotonic()
        pipe.finish()
        pipe.state["detail"] = f"demo replay done (x{speed:g})"
        while hold:  # stay "connected" with no ticks: the watchdog turns the feed stale
            pipe.write_status()
            time.sleep(1.0)
    except (KeyboardInterrupt, _Stop):
        pass
    pipe.state["connected"] = False
    pipe.state["detail"] = "demo stopped"
    pipe.write_status()
    return 0
