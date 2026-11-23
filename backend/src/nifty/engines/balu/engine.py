"""Engine `pine.balu_zone` (v1, in progress): port of reference/pine/Balu_Zone_Scalper_v2.pine.

C09 implements steps 1-6 of the bar order (docs/pine/BALU-3.md); C10/C11 register the rest through
`steps.STEPS` without editing this file."""

from importlib import import_module
from typing import Any

from nifty.contracts import TF_MINUTES, Bar, EngineOutput
from nifty.engines.balu import steps
from nifty.engines.balu.params import BaluParams
from nifty.engines.base import register_engine
from nifty.engines.context import EngineContext

for _m in steps.STEP_MODULES:
    import_module(_m)


class BaluZoneEngine:
    id = "pine.balu_zone"
    version = "1"
    default_timeframe = "5m"
    Params = BaluParams
    plots = steps.PLOT_SPECS
    warmup_bars = 100 + 5  # 100 + flowSlopeLen (default): the 100-bar flow window must be full

    def __init__(self, params: BaluParams, ctx: EngineContext) -> None:
        self.p, self.ctx = params, ctx
        self.tf_min = 375.0 if ctx.timeframe == "1d" else float(TF_MINUTES[ctx.timeframe])
        self.slots: dict[str, steps.Slot] = {n: f(params) for n, f in steps.SLOT_FACTORIES.items()}

    def on_bar(self, bar: Bar) -> EngineOutput:
        f = steps.BarFrame(bar=bar, out=EngineOutput())
        for n in range(1, len(steps.STEP_NAMES) + 1):  # Pine is top-to-bottom
            fn = steps.STEPS.get(n)
            if fn is not None:
                fn(self, f)
        return f.out

    def on_provisional(self, bar: Bar) -> EngineOutput:
        return EngineOutput()  # pressure only (C11)

    def snapshot(self) -> dict[str, Any]:
        return {n: s.state() for n, s in self.slots.items()}

    def restore(self, snap: dict[str, Any]) -> None:
        for n, s in self.slots.items():
            s.load(snap[n])

    def panel(self) -> dict[str, Any] | None:
        return None  # BALU-3


register_engine(BaluZoneEngine, ready=False)
