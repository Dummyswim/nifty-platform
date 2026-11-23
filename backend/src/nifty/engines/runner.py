"""Engine runner: batch, incremental, restart, provisional. Pure (no DB, no network, no clock).

Contract with engines (D14): they see only finalized chart bars, one `on_bar` per bar, with the
aux API of EngineContext bounded by the bar. The runner stamps the event envelope, assigns `seq`
per (bar_start, event_type) and sanitises NaN to None, so batch == incremental == restart.

Chart bars carry no `quality_flags`: gap/partial flags are derived from the rest of the dataset
(later bars), which is lookahead and differs between batch and incremental.
"""

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from nifty.contracts import (
    TF_MINUTES,
    Bar,
    EngineEvent,
    EngineOutput,
    EngineParams,
    Instrument,
    OverlayElement,
    TradeRecord,
    config_hash,
    make_event_id,
)
from nifty.engines.base import Engine, get_engine
from nifty.engines.context import EngineContext
from nifty.marketdata.resample import resample
from nifty.timeutil import Calendar

Plots = dict[str, float | None]


@dataclass
class RunResult:
    engine_id: str
    engine_version: str
    config_hash: str
    instrument_id: str
    timeframe: str
    source_id: str
    params: dict[str, Any]
    bars: list[Bar] = field(default_factory=list)
    plots: list[tuple[datetime, Plots]] = field(default_factory=list)
    events: list[EngineEvent] = field(default_factory=list)
    overlays: list[OverlayElement] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    panel: dict[str, Any] | None = None
    provisional: list[dict[str, Any]] = field(default_factory=list)


def clean(x: Any) -> Any:
    """NaN/inf -> None (JSON and Postgres JSONB cannot hold them), recursively."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def _strip(b: Bar) -> Bar:
    return b.model_copy(update={"quality_flags": ()})


class ChartBuilder:
    """Incremental session-anchored resampler emitting only bars that are final at that moment."""

    def __init__(self, tf: str, cal: Calendar) -> None:
        self.tf, self.cal = tf, cal
        self._key: tuple[date, datetime] | None = None
        self._members: list[Bar] = []

    def _key_of(self, m: Bar) -> tuple[date, datetime]:
        d = self.cal.session_date(m.bar_start_utc)
        open_, _ = self.cal.session_bounds(d)
        if self.tf == "1d":
            return d, open_
        n = TF_MINUTES[self.tf]
        idx = int((m.bar_start_utc - open_) / timedelta(minutes=1)) // n
        return d, open_ + idx * n * timedelta(minutes=1)

    def _end(self, key: tuple[date, datetime]) -> datetime:
        close = self.cal.session_bounds(key[0])[1]
        return (
            close
            if self.tf == "1d"
            else min(key[1] + timedelta(minutes=TF_MINUTES[self.tf]), close)
        )

    def flush_before(self, m: Bar) -> Bar | None:
        """Emit the open bucket when `m` belongs to a later one (a later bar proves it is done)."""
        if self._members and self._key_of(m) != self._key:
            return self._emit()
        return None

    def add(self, m: Bar) -> Bar | None:
        key = self._key_of(m)
        self._key = key
        self._members.append(m)
        return self._emit() if m.bar_end_utc >= self._end(key) else None

    def partial(self) -> Bar | None:
        if not self._members:
            return None
        b = resample(self._members, self.tf, self.cal)[0]
        return _strip(b).model_copy(update={"finalized": False})

    def _emit(self) -> Bar:
        b = resample(self._members, self.tf, self.cal)[0]
        self._members, self._key = [], None
        return _strip(b).model_copy(update={"finalized": True})


class _Run:
    def __init__(
        self,
        engine_id: str,
        params: Any,
        timeframe: str | None,
        instrument: Instrument | None,
        bars_1m: Sequence[Bar],
        calendar: Calendar | None,
        source_id: str,
        allow_unready: bool,
        proxy_volume_1m: dict[datetime, float] | None,
    ) -> None:
        spec = get_engine(engine_id, allow_unready)
        self.cls: type[Engine] = spec.cls
        if isinstance(params, EngineParams):
            self.params = params
        else:
            self.params = self.cls.Params.model_validate(params or {})
        self.tf = timeframe or self.cls.default_timeframe
        self.cal = calendar or Calendar.load()
        first = bars_1m[0] if bars_1m else None
        self.instrument = instrument or Instrument(
            instrument_id=first.instrument_id if first else "unknown",
            provider="kite" if first and first.provider == "kite" else "csv",
            tradingsymbol=first.instrument_id if first else "unknown",
        )
        self.proxy = proxy_volume_1m
        self.ctx = EngineContext(self.instrument, self.tf, self.cal, proxy_volume_1m)
        self.engine = self.cls(self.params, self.ctx)
        self.cfg = config_hash(self.cls.id, self.cls.version, self.params)
        self.result = RunResult(
            engine_id=self.cls.id,
            engine_version=self.cls.version,
            config_hash=self.cfg,
            instrument_id=self.instrument.instrument_id,
            timeframe=self.tf,
            source_id=source_id,
            params=self.params.model_dump(mode="json"),
        )

    def _stamp(
        self, bar: Bar, out: EngineOutput, provisional: bool, available_at: datetime
    ) -> list[EngineEvent]:
        seq: dict[str, int] = defaultdict(int)
        events: list[EngineEvent] = []
        for ev in out.events:
            n = seq[ev.event_type]
            seq[ev.event_type] += 1
            events.append(
                EngineEvent(
                    event_id=make_event_id(
                        self.cls.id,
                        self.cfg,
                        self.instrument.instrument_id,
                        self.tf,
                        bar.bar_start_utc,
                        ev.event_type,
                        n,
                        provisional,
                    ),
                    seq=n,
                    event_type=ev.event_type,
                    engine_id=self.cls.id,
                    engine_version=self.cls.version,
                    config_hash=self.cfg,
                    instrument_id=self.instrument.instrument_id,
                    source_id=self.result.source_id,
                    timeframe=self.tf,
                    event_time_utc=available_at,
                    available_at_utc=available_at,
                    bar_start_utc=bar.bar_start_utc,
                    bar_end_utc=bar.bar_end_utc,
                    confirmed_or_provisional="provisional" if provisional else "confirmed",
                    price_basis=ev.price_basis,
                    payload=clean(ev.payload),
                )
            )
        return events

    def on_chart_bar(self, bar: Bar) -> None:
        out = self.engine.on_bar(bar)
        r = self.result
        r.bars.append(bar)
        r.plots.append((bar.bar_start_utc, clean(out.plots)))
        r.events.extend(self._stamp(bar, out, False, bar.bar_end_utc))
        for o in out.overlay_ops:
            el = OverlayElement.model_validate(clean(o.model_dump()))  # NaN prices -> None
            r.overlays.append(
                el.model_copy(
                    update={
                        "engine_id": self.cls.id,
                        "avail_at_utc": el.avail_at_utc or bar.bar_end_utc,
                    }
                )
            )
        for t in out.trades:
            try:
                r.trades.append(TradeRecord.model_validate(clean(t.model_dump())))
            except ValidationError as e:
                raise ValueError(
                    f"{self.cls.id} emitted a trade with NaN in a required field"
                ) from e
        r.panel = clean(self.engine.panel())

    def on_partial(self, bar: Bar, available_at: datetime) -> None:
        self.ctx.provisional = True
        try:
            out = self.engine.on_provisional(bar)
        finally:
            self.ctx.provisional = False
        self.result.provisional.append(
            {
                "bar_start_utc": bar.bar_start_utc,
                "available_at_utc": available_at,
                "plots": clean(out.plots),
                "events": self._stamp(bar, out, True, available_at),
            }
        )

    def restart(self, seen: Sequence[Bar]) -> None:
        """snapshot -> JSON round-trip (no NaN allowed) -> brand-new engine and context."""
        snap = json.loads(json.dumps(self.engine.snapshot(), allow_nan=False))
        ctx = EngineContext(self.instrument, self.tf, self.cal, self.proxy)
        for b in seen:
            ctx.append_1m(b)
        engine = self.cls(self.params, ctx)
        engine.restore(snap)
        self.ctx, self.engine = ctx, engine


def run_batch(
    engine_id: str,
    params: Any,
    bars_1m: Sequence[Bar],
    timeframe: str | None = None,
    *,
    instrument: Instrument | None = None,
    calendar: Calendar | None = None,
    source_id: str = "batch",
    allow_unready: bool = False,
    proxy_volume_1m: dict[datetime, float] | None = None,
) -> RunResult:
    """Resample to `timeframe`, then loop `on_bar` over the finalized bars."""
    run = _Run(
        engine_id, params, timeframe, instrument, bars_1m, calendar, source_id,
        allow_unready, proxy_volume_1m,
    )  # fmt: skip
    chart = [_strip(b) for b in resample(bars_1m, run.tf, run.cal) if b.finalized]
    i = 0
    for cb in chart:
        while i < len(bars_1m) and bars_1m[i].bar_start_utc < cb.bar_end_utc:
            if bars_1m[i].timeframe == "1m":  # chart-tf input (TV golden) has no aux 1m buffer
                run.ctx.append_1m(bars_1m[i])
            i += 1
        run.on_chart_bar(cb)
    return run.result


def run_incremental(
    engine_id: str,
    params: Any,
    bars_1m: Iterable[Bar],
    timeframe: str | None = None,
    *,
    instrument: Instrument | None = None,
    calendar: Calendar | None = None,
    source_id: str = "live",
    allow_unready: bool = False,
    proxy_volume_1m: dict[datetime, float] | None = None,
    provisional: bool = False,
    restart_after: int | None = None,
) -> RunResult:
    """Feed 1m bars one at a time; finalized chart bars are emitted as they become final.

    `restart_after=k` swaps in a restored engine after k chart bars. `provisional=True` also
    calls `on_provisional` with the forming bar after each 1m bar.
    """
    seq = list(bars_1m)
    run = _Run(
        engine_id, params, timeframe, instrument, seq, calendar, source_id,
        allow_unready, proxy_volume_1m,
    )  # fmt: skip
    builder = ChartBuilder(run.tf, run.cal)
    seen: list[Bar] = []
    n_chart = 0

    def deliver(bar: Bar) -> None:
        nonlocal n_chart
        run.on_chart_bar(bar)
        n_chart += 1
        if restart_after is not None and n_chart == restart_after:
            run.restart(seen)

    for m in seq:
        pre = builder.flush_before(m)  # before m enters the aux buffer: it is in the future
        if pre is not None:
            deliver(pre)
        run.ctx.append_1m(m)
        seen.append(m)
        post = builder.add(m)
        if post is not None:
            deliver(post)
        elif provisional:
            part = builder.partial()
            if part is not None:
                run.on_partial(part, m.bar_end_utc)
    return run.result


def run_with_restart(
    engine_id: str, params: Any, bars_1m: Iterable[Bar], timeframe: str | None = None,
    *, cut: int, **kw: Any,
) -> RunResult:  # fmt: skip
    """Incremental run that snapshots after `cut` chart bars and continues on a restored engine."""
    return run_incremental(engine_id, params, bars_1m, timeframe, restart_after=cut, **kw)
