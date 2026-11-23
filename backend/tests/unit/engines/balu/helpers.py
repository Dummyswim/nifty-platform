"""Harness for Balu tests: hand-specified 5m bars (each also expanded into five 1m bars so the aux
buffer, prior day and HTF buckets behave as in a real run) fed straight to the engine."""

import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

import nifty.engines.balu  # noqa: F401  (registers pine.balu_zone, ready=False)
from nifty.contracts import Bar, EngineOutput, Instrument
from nifty.engines.balu.engine import BaluZoneEngine
from nifty.engines.balu.params import BaluParams
from nifty.engines.context import EngineContext
from tests.helpers import CAL, NOW

INST = Instrument(instrument_id="csv:T", provider="csv", tradingsymbol="T", tick_size=0.05)
NaN = math.nan
OHLC = tuple[float, float, float, float]


def bar1(start: datetime, o: float, h: float, lo: float, c: float, tf: str, mins: int) -> Bar:
    return Bar(
        instrument_id="csv:T", provider="csv", timeframe=tf,  # type: ignore[arg-type]
        bar_start_utc=start, bar_end_utc=start + timedelta(minutes=mins), open=o, high=h, low=lo,
        close=c, volume=0.0, volume_kind="absent", received_at_utc=NOW,
    )  # fmt: skip


def one_min(start: datetime, o: float, h: float, lo: float, c: float) -> list[Bar]:
    """Five 1m bars whose 5m aggregate is exactly (o, h, lo, c)."""
    p = [(o, o, o, o), (o, h, o, h), (h, h, lo, lo), (lo, lo, lo, lo), (lo, max(lo, c), lo, c)]
    return [bar1(start + timedelta(minutes=i), *q, "1m", 1) for i, q in enumerate(p)]


class Harness:
    def __init__(self, tf: str = "5m", **params: Any) -> None:
        self.tf, self.mins = tf, {"5m": 5, "15m": 15}[tf]
        self.p = BaluParams(**params)
        self.ctx = EngineContext(INST, tf, CAL)
        self.engine = BaluZoneEngine(self.p, self.ctx)
        self.outs: list[EngineOutput] = []
        self.starts: list[datetime] = []

    def day(self, d: date, specs: Sequence[OHLC]) -> list[EngineOutput]:
        open_, _ = CAL.session_bounds(d)
        res = []
        for i, (o, h, lo, c) in enumerate(specs):
            start = open_ + timedelta(minutes=self.mins * i)
            for m in one_min(start, o, h, lo, c) if self.mins == 5 else []:
                self.ctx.append_1m(m)
            if self.mins != 5:  # coarser charts: 1m members are flat copies of the bar
                for k in range(self.mins):
                    self.ctx.append_1m(bar1(start + timedelta(minutes=k), o, h, lo, c, "1m", 1))
            out = self.engine.on_bar(bar1(start, o, h, lo, c, self.tf, self.mins))
            self.outs.append(out)
            self.starts.append(start)
            res.append(out)
        return res

    def plot(self, name: str) -> list[float]:
        return [o.plots[name] if o.plots[name] is not None else NaN for o in self.outs]  # type: ignore[misc]


D1, D2, D3 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)
