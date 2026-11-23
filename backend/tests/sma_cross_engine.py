"""Test-only engine `test.sma_cross` (never registered in production)."""

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pydantic import Field

import nifty.engines.pinekit as pk
from nifty.contracts import (
    Bar,
    EngineOutput,
    EngineParams,
    Ev,
    OverlayElement,
    PlotSpec,
    UiParams,
)
from nifty.engines.base import register_engine, unregister_engine
from nifty.engines.context import EngineContext


class SmaCrossUi(UiParams):
    color: str = "#0066ff"
    show_markers: bool = True


class SmaCrossParams(EngineParams):
    fast: int = 3
    slow: int = 5
    ui: SmaCrossUi = Field(default_factory=SmaCrossUi)


class SmaCross:
    id = "test.sma_cross"
    version = "1"
    default_timeframe = "5m"
    Params = SmaCrossParams
    plots = [PlotSpec(name="fast"), PlotSpec(name="slow"), PlotSpec(name="prior_close")]
    warmup_bars = 5

    def __init__(self, params: SmaCrossParams, ctx: EngineContext) -> None:
        self.p, self.ctx = params, ctx
        self.fast, self.slow = pk.Sma(params.fast), pk.Sma(params.slow)
        self.up, self.dn = pk.Crossover(), pk.Crossunder()
        self.htf_close = pk.NaN
        self.n = 0

    def _outputs(
        self, bar: Bar, fast: pk.Sma, slow: pk.Sma, up: pk.Crossover, dn: pk.Crossunder
    ) -> tuple[EngineOutput, float]:
        f, s = fast.update(bar.close), slow.update(bar.close)
        out = EngineOutput()
        prior = self.ctx.prior_day(bar)
        step = self.ctx.htf(bar, "15m")
        htf = step.completed.close if step.completed is not None else self.htf_close
        sub = len(self.ctx.sub_bars(bar, "1m")) if self.ctx.timeframe != "1m" else 0
        out.plots = {
            "fast": f,
            "slow": s,
            "prior_close": prior.close if prior else pk.NaN,
            "htf_close": htf,
            "sub_n": float(sub),
        }
        if up.update(f, s):
            out.events.append(Ev("signal", {"dir": "up", "close": bar.close}, "close"))
            out.overlay_ops.append(
                OverlayElement(
                    id=f"m{bar.bar_start_utc.isoformat()}",
                    kind="marker",
                    t0=bar.bar_start_utc,
                    p0=bar.low,
                    style={"role": "bull", "color": self.p.ui.color},
                )
            )
        if dn.update(f, s):
            out.events.append(Ev("signal", {"dir": "down", "close": bar.close}, "close"))
            out.events.append(Ev("signal", {"dir": "down-extra", "close": bar.close}))
        return out, htf

    def on_bar(self, bar: Bar) -> EngineOutput:
        out, self.htf_close = self._outputs(bar, self.fast, self.slow, self.up, self.dn)
        self.n += 1
        return out

    def on_provisional(self, bar: Bar) -> EngineOutput:
        # work on copies: confirmed state must not change
        out, _ = self._outputs(bar, *copy.deepcopy((self.fast, self.slow, self.up, self.dn)))
        return out

    def snapshot(self) -> dict[str, Any]:
        return {
            "fast": self.fast.state(),
            "slow": self.slow.state(),
            "up": self.up.state(),
            "dn": self.dn.state(),
            "htf_close": pk.enc([self.htf_close])[0],
            "n": self.n,
        }

    def restore(self, snap: dict[str, Any]) -> None:
        self.fast.load(snap["fast"])
        self.slow.load(snap["slow"])
        self.up.load(snap["up"])
        self.dn.load(snap["dn"])
        self.htf_close = pk.dec([snap["htf_close"]])[0]
        self.n = snap["n"]

    def panel(self) -> dict[str, Any] | None:
        return {"rows": [{"label": "bars", "value": self.n, "role": "neutral"}]}


@contextmanager
def registered(ready: bool = True) -> Iterator[type[SmaCross]]:
    register_engine(SmaCross, ready=ready)
    try:
        yield SmaCross
    finally:
        unregister_engine(SmaCross.id)
