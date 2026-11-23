"""EngineContext: instrument facts plus the causal aux API backed by an append-only 1m buffer.

Every query is bounded by the bar it is asked about (its own end, or earlier sessions), never by
"the end of the buffer", so appending future bars cannot change an answer.
"""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from nifty.contracts import TF_MINUTES, Bar, Instrument
from nifty.engines.pinekit.session import bucket_start
from nifty.marketdata.resample import resample
from nifty.timeutil import Calendar

_MIN = timedelta(minutes=1)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PriorDay:
    date: date  # the previous session present in the data (not the calendar's previous weekday)
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class HtfStep:
    new_bar: bool
    completed: Bar | None


class EngineContext:
    def __init__(
        self,
        instrument: Instrument,
        timeframe: str,
        calendar: Calendar,
        proxy_volume_1m: dict[datetime, float] | None = None,
    ) -> None:
        self.instrument = instrument
        self.timeframe = timeframe
        self.calendar = calendar
        self.provisional = False  # set by the runner while calling on_provisional
        self._proxy = proxy_volume_1m or {}
        self._bars: list[Bar] = []
        self._starts: list[datetime] = []
        self._sess_dates: list[date] = []
        self._sess: dict[date, list[float]] = {}  # date -> [high, low, close]
        self._htf: dict[str, dict[datetime, list[Bar]]] = {}
        self._htf_order: dict[str, list[datetime]] = {}  # bucket starts, ascending

    @property
    def mintick(self) -> float:
        if self.instrument.tick_size is None:
            raise ConfigError("instrument has no tick_size; never invented")
        return self.instrument.tick_size

    # ---- buffer (runner only) -------------------------------------------------------------
    def append_1m(self, bar: Bar) -> None:
        if bar.timeframe != "1m":
            raise ValueError("aux buffer takes 1m bars")
        if self._starts and bar.bar_start_utc <= self._starts[-1]:
            raise ValueError("1m bars must be appended in strictly increasing time order")
        self._bars.append(bar)
        self._starts.append(bar.bar_start_utc)
        d = self.calendar.session_date(bar.bar_start_utc)
        s = self._sess.get(d)
        if s is None:
            self._sess[d] = [bar.high, bar.low, bar.close]
            self._sess_dates.append(d)
        else:
            s[0], s[1], s[2] = max(s[0], bar.high), min(s[1], bar.low), bar.close
        for res, buckets in self._htf.items():
            self._add_htf(res, buckets, bar)

    # ---- aux API ----------------------------------------------------------------------------
    def prior_day(self, bar: Bar) -> PriorDay | None:
        d = self.calendar.session_date(bar.bar_start_utc)
        i = bisect_left(self._sess_dates, d)  # sessions strictly before d only
        if i == 0:
            return None
        pd = self._sess_dates[i - 1]
        h, lo, c = self._sess[pd]
        return PriorDay(pd, h, lo, c)

    def htf(self, bar: Bar, res: str) -> HtfStep:
        buckets = self._htf_buckets(res)
        key = self._bucket_start(res, bar.bar_start_utc)
        members = buckets.get(key)
        new_bar = members is not None and members[0].bar_start_utc >= bar.bar_start_utc
        if not new_bar:
            return HtfStep(False, None)
        order = self._htf_order[res]
        i = bisect_left(order, key)
        if i == 0:
            return HtfStep(True, None)
        done = resample(buckets[order[i - 1]], res, self.calendar)[0]
        return HtfStep(True, done.model_copy(update={"quality_flags": (), "finalized": True}))

    def sub_bars(self, bar: Bar, res: str) -> list[Bar]:
        chart = self._tf_minutes(self.timeframe)
        r = TF_MINUTES.get(res)
        if r is None or r >= chart or chart % r:
            raise ConfigError(f"sub_bars({res}) must be shorter than and divide {self.timeframe}")
        lo = bisect_left(self._starts, bar.bar_start_utc)
        hi = bisect_left(self._starts, bar.bar_end_utc)  # never past the bar's own end
        window = self._bars[lo:hi]
        if res == "1m":
            return list(window)
        out = resample(window, res, self.calendar) if window else []
        return out if self.provisional else [b for b in out if b.finalized]

    def proxy_volume(self, bar: Bar) -> float | None:
        lo = bisect_left(self._starts, bar.bar_start_utc)
        hi = bisect_left(self._starts, bar.bar_end_utc)
        total = 0.0
        for s in self._starts[lo:hi]:
            v = self._proxy.get(s)
            if v is None:
                return None
            total += v
        return total if hi > lo else None

    # ---- helpers ----------------------------------------------------------------------------
    @staticmethod
    def _tf_minutes(tf: str) -> int:
        return 375 if tf == "1d" else TF_MINUTES[tf]

    def _bucket_start(self, res: str, t: datetime) -> datetime:
        return bucket_start(res, t, self.calendar)

    def _htf_buckets(self, res: str) -> dict[datetime, list[Bar]]:
        if res != "1d" and res not in TF_MINUTES:
            raise ConfigError(f"unknown timeframe {res}")
        if res not in self._htf:
            self._htf[res] = {}
            self._htf_order[res] = []
            for b in self._bars:
                self._add_htf(res, self._htf[res], b)
        return self._htf[res]

    def _add_htf(self, res: str, buckets: dict[datetime, list[Bar]], bar: Bar) -> None:
        key = self._bucket_start(res, bar.bar_start_utc)
        if key not in buckets:
            self._htf_order[res].append(key)
            buckets[key] = []
        buckets[key].append(bar)
