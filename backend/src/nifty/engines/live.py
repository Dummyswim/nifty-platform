"""Live engine runner (pure; persistence lives in the collector). One `LiveRun` = one engine over
one instrument, fed finalized 1m bars as they arrive, producing the same outputs as
`run_incremental` over the same bars (D14). Restart = a fresh LiveRun replays the stored 1m bars;
outputs carry stable ids/ord so writing them again is idempotent."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from nifty.contracts import Bar, EngineEvent, Instrument, OverlayElement, TradeRecord
from nifty.engines.runner import ChartBuilder, _Run
from nifty.marketdata.resample import resample
from nifty.timeutil import Calendar


@dataclass
class LiveDelta:
    chart_bars: list[Bar] = field(default_factory=list)
    plots: list[tuple[datetime, dict[str, float | None]]] = field(default_factory=list)
    events: list[tuple[int, EngineEvent]] = field(default_factory=list)  # (ord, event)
    overlays: list[tuple[int, OverlayElement]] = field(default_factory=list)  # (ord, element)
    trades: list[TradeRecord] = field(default_factory=list)
    panel: dict[str, Any] | None = None

    def empty(self) -> bool:
        return not (self.chart_bars or self.plots or self.events or self.overlays)


class LiveRun:
    def __init__(
        self,
        engine_id: str,
        params: Any,
        instrument: Instrument,
        timeframe: str | None = None,
        calendar: Calendar | None = None,
        source_id: str | None = None,
        proxy_volume_1m: dict[datetime, float] | None = None,
    ) -> None:
        self.source_id = source_id or f"live:{instrument.instrument_id}"
        self._run = _Run(
            engine_id, params, timeframe, instrument, [], calendar, self.source_id, False,
            proxy_volume_1m,
        )  # fmt: skip
        self._builder = ChartBuilder(self._run.tf, self._run.cal)
        self.engine_id, self.timeframe = engine_id, self._run.tf
        self.config_hash = self._run.cfg
        self.version = self._run.cls.version
        self.params = self._run.result.params
        self.n_events = 0
        self.n_overlays = 0
        self.panel: dict[str, Any] | None = None
        self.last_1m: datetime | None = None

    def _collect(self) -> LiveDelta:
        r = self._run.result
        d = LiveDelta(
            chart_bars=list(r.bars), plots=list(r.plots), trades=list(r.trades), panel=r.panel
        )
        d.events = [(self.n_events + i, e) for i, e in enumerate(r.events)]
        d.overlays = [(self.n_overlays + i, o) for i, o in enumerate(r.overlays)]
        self.n_events += len(r.events)
        self.n_overlays += len(r.overlays)
        for lst in (r.bars, r.plots, r.events, r.overlays, r.trades):
            lst.clear()  # live runs are long: do not accumulate what has been handed out
        if r.panel is not None:
            self.panel = r.panel
        return d

    def feed(self, m: Bar) -> LiveDelta:
        """One finalized 1m bar (strictly later than the previous one)."""
        if self.last_1m is not None and m.bar_start_utc <= self.last_1m:
            return LiveDelta()
        self.last_1m = m.bar_start_utc
        pre = self._builder.flush_before(m)  # before m enters the aux buffer: it is in the future
        if pre is not None:
            self._run.on_chart_bar(pre)
        self._run.ctx.append_1m(m)
        post = self._builder.add(m)
        if post is not None:
            self._run.on_chart_bar(post)
        return self._collect()

    def provisional(self, forming: Bar) -> dict[str, Any] | None:
        """Plots/events for the chart bar including the forming 1m bar; never changes state."""
        if self.last_1m is not None and forming.bar_start_utc <= self.last_1m:
            return None
        members = [*self._builder._members, forming]  # noqa: SLF001
        try:
            part = resample(members, self.timeframe, self._run.cal)[0]
        except ValueError:
            return None
        part = part.model_copy(update={"finalized": False, "quality_flags": ()})
        self._run.on_partial(part, forming.bar_end_utc)
        out = self._run.result.provisional.pop()
        self._run.result.provisional.clear()
        return out
