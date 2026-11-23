"""Tick -> 1m bar builder (D08, D20, D21). Pure: no clock, no I/O.

Bars are keyed by the tick's EXCHANGE timestamp (UTC minute floor), never the wall clock. A bar is
finalized when a tick of a later minute arrives. Out-of-order ticks inside the open minute only
widen high/low and can move open/close by timestamp; ticks for an already finalized minute are
counted as late and dropped (a finalized bar is never rewritten live; EOD reconcile adds a
revision). Volume is the delta of the day's cumulative traded volume (the index has none, so
volume_kind is absent).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from nifty.collector.packets import PacketTick
from nifty.contracts import Bar
from nifty.timeutil import Calendar, utcnow

ONE_MIN = timedelta(minutes=1)


def minute_floor(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


@dataclass
class _Open:
    start: datetime
    o: float
    h: float
    lo: float
    c: float
    t_first: datetime
    t_last: datetime
    base_vol: float | None  # cumulative volume before this minute's first tick
    last_vol: float | None
    seen: set[tuple[datetime, float, float | None]]


class BarBuilder:
    def __init__(
        self,
        instrument_id: str,
        is_index: bool,
        calendar: Calendar | None = None,
        provider: str = "kite",
    ) -> None:
        self.instrument_id, self.is_index, self.provider = instrument_id, is_index, provider
        self.cal = calendar or Calendar.load()
        self._open: _Open | None = None
        self._last_final_start: datetime | None = None
        self._cum_prev: float | None = (
            None  # cumulative volume at the end of the last finalized bar
        )
        self._cum_day: object = None
        self.late_ticks = 0
        self.dup_ticks = 0
        self.dropped_offsession = 0

    # ---- helpers ---------------------------------------------------------------------------
    def _in_session(self, ts: datetime) -> bool:
        d = self.cal.session_date(ts)
        if not self.cal.is_session_day(d):
            return False
        lo, hi = self.cal.session_bounds(d)
        return lo <= ts < hi

    def _bar(self, o: _Open, finalized: bool) -> Bar:
        if self.is_index or o.last_vol is None:
            vol, kind = 0.0, "absent"
        else:
            base = o.base_vol if o.base_vol is not None and o.base_vol <= o.last_vol else 0.0
            vol, kind = o.last_vol - base, "exchange"
        return Bar(
            instrument_id=self.instrument_id, provider=self.provider, timeframe="1m",
            bar_start_utc=o.start, bar_end_utc=o.start + ONE_MIN, open=o.o, high=o.h, low=o.lo,
            close=o.c, volume=vol, volume_kind=kind,  # type: ignore[arg-type]
            finalized=finalized, received_at_utc=utcnow(),
            quality_flags=("volume_absent",) if kind == "absent" else (),
        )  # fmt: skip

    # ---- API ---------------------------------------------------------------------------------
    def on_tick(self, t: PacketTick, received: datetime | None = None) -> list[Bar]:
        """Feed one tick; returns the bars finalized by it (0 or 1)."""
        ts = t.exchange_ts or received
        if ts is None:
            return []
        if not self._in_session(ts):
            self.dropped_offsession += 1
            return []
        start = minute_floor(ts)
        out: list[Bar] = []
        cur = self._open
        if self._last_final_start is not None and start <= self._last_final_start:
            self.late_ticks += 1
            return []
        if cur is not None and start > cur.start:
            out.append(self._bar(cur, True))
            self._last_final_start = cur.start
            self._cum_prev = cur.last_vol if cur.last_vol is not None else self._cum_prev
            cur = self._open = None
        key = (ts, t.ltp, t.volume)
        if cur is None:
            day = self.cal.session_date(ts)
            if self._cum_day != day:  # new trading day: the cumulative volume restarts at 0
                self._cum_prev, self._cum_day = 0.0, day
            self._open = _Open(
                start, t.ltp, t.ltp, t.ltp, t.ltp, ts, ts, self._cum_prev, t.volume, {key}
            )
            return out
        if key in cur.seen:
            self.dup_ticks += 1
            return out
        cur.seen.add(key)
        cur.h, cur.lo = max(cur.h, t.ltp), min(cur.lo, t.ltp)
        if ts < cur.t_first:
            cur.o, cur.t_first = t.ltp, ts
        if ts >= cur.t_last:
            cur.c, cur.t_last = t.ltp, ts
            if t.volume is not None:
                cur.last_vol = t.volume if cur.last_vol is None else max(cur.last_vol, t.volume)
        return out

    def provisional(self) -> Bar | None:
        """The forming minute as a non-final bar (callers throttle to <= 4 per second)."""
        return None if self._open is None else self._bar(self._open, False)

    def flush(self) -> Bar | None:
        """Finalize the open minute (session end / shutdown)."""
        if self._open is None:
            return None
        b = self._bar(self._open, True)
        self._last_final_start = self._open.start
        self._cum_prev = self._open.last_vol if self._open.last_vol is not None else self._cum_prev
        self._open = None
        return b


class Throttle:
    """Allow at most one call per `every` seconds on an injected monotonic clock."""

    def __init__(self, every: float = 0.25) -> None:
        self.every, self._last = every, float("-inf")

    def ok(self, now: float) -> bool:
        if now - self._last >= self.every:
            self._last = now
            return True
        return False


class Watchdog:
    """Silence detector on an injected monotonic clock (tick arrival, not exchange time)."""

    def __init__(self, threshold: float = 15.0) -> None:
        self.threshold, self.last = threshold, None

    last: float | None

    def beat(self, now: float) -> None:
        self.last = now

    def age(self, now: float) -> float | None:
        return None if self.last is None else now - self.last

    def stale(self, now: float) -> bool:
        a = self.age(now)
        return a is not None and a > self.threshold
