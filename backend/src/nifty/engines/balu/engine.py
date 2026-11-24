"""Engine `pine.balu_zone` v1: port of reference/pine/Balu_Zone_Scalper_v2.pine.

The 15 steps of the bar order (docs/pine/BALU-3.md) are registered through `steps.STEPS` by the
modules in `steps.STEP_MODULES`; this file only runs them, snapshots their slots and builds the panel."""

from importlib import import_module
from typing import Any

from nifty.contracts import TF_MINUTES, Bar, EngineOutput
from nifty.engines.balu import steps
from nifty.engines.balu.params import BaluParams
from nifty.engines.base import register_engine
from nifty.engines.context import EngineContext

for _m in steps.STEP_MODULES:
    import_module(_m)


SNAPSHOT_VERSION = 1
# Only these plots are drawn on the chart; every other series is data-window only (role "hidden"),
# which keeps the chart to the overlay pane and still exports them for parity.
VISIBLE_PLOTS = {"golden", "moving_line", "or_high", "or_low"}
steps.PLOT_SPECS[:] = [
    s if s.name in VISIBLE_PLOTS else s.model_copy(update={"role": "hidden"})
    for s in steps.PLOT_SPECS
]


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
        out = EngineOutput()  # only registered hooks run (pressure); they never mutate engine state
        for hook in steps.PROVISIONAL:
            o = hook(self, bar)
            out.plots.update(o.plots)
            out.events += o.events
        return out

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe (NaN as None). Schema version SNAPSHOT_VERSION; one entry per registered slot."""
        return {"v": SNAPSHOT_VERSION, "slots": {n: s.state() for n, s in self.slots.items()}}

    def restore(self, snap: dict[str, Any]) -> None:
        if snap.get("v") != SNAPSHOT_VERSION:
            raise ValueError(f"unsupported balu snapshot version {snap.get('v')!r}")
        for n, s in self.slots.items():
            s.load(snap["slots"][n])

    def panel(self) -> dict[str, Any] | None:
        return steps.PANEL[0](self) if steps.PANEL else None


register_engine(BaluZoneEngine, ready=True)
