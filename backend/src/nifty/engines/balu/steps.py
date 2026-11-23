"""The ordered step contract of the whole engine (docs/pine/BALU-3.md "Whole-engine bar order").

`STEPS[n]` runs on every finalized bar, n = 1..15, top-to-bottom as Pine does. C09 fills 1-6;
C10 registers 7-12 and C11 13-15 by decorating functions in NEW modules and listing those modules
in `STEP_MODULES`; the engine itself is never edited. State that must survive a restart is
registered with `register_slot`: any object with `state()` / `load(st)` (JSON-safe, NaN as None).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from nifty.contracts import Bar, EngineOutput, PlotSpec
from nifty.engines.pinekit import NaN

if TYPE_CHECKING:
    from nifty.engines.balu.engine import BaluZoneEngine
    from nifty.engines.balu.params import BaluParams

STEP_NAMES = (
    "session_anchors", "pivots_htf", "pool_adds", "golden", "moving_line", "divergence",
    "zone_housekeeping", "zone_rebuild", "key_levels", "location", "pressure", "sweeps",
    "path_history", "panel_snapshot", "alerts",
)  # fmt: skip


class Slot(Protocol):
    def state(self) -> dict[str, Any]: ...
    def load(self, st: dict[str, Any]) -> None: ...


@dataclass
class BarFrame:
    """Per-bar scratch shared by the steps (values computed earlier in the same bar)."""

    bar: Bar
    out: EngineOutput
    atr: float = NaN
    in_session: bool = True
    new_session: bool = False
    # step 1
    pd_h: float = NaN
    pd_l: float = NaN
    pd_c: float = NaN
    pp: float = NaN
    r1: float = NaN
    s1: float = NaN
    # step 2
    s_ph: float = NaN
    s_pl: float = NaN
    htf_new_bar: bool = False
    htf_ph: float = NaN
    htf_pl: float = NaN
    # step 4
    gold_val: float = NaN
    gold_state: int = 0
    regime_idx: int = 1
    gold_anchor: str = ""
    # step 5
    cvd: float = NaN
    flow_ready: bool = False
    flow_state: int = 0
    # step 6
    bear_div: bool = False
    bull_div: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# on_provisional hooks (C10 pressure): (engine, forming bar) -> EngineOutput; read-only
PROVISIONAL: list[Callable[[Any, Bar], EngineOutput]] = []
PLOT_SPECS: list[PlotSpec] = []  # modules append their PlotSpecs (the engine exposes this list)
Step = Callable[["BaluZoneEngine", BarFrame], None]
STEPS: dict[int, Step] = {}
SLOT_FACTORIES: dict[str, Callable[["BaluParams"], Slot]] = {}
# modules imported by the engine so their @step / @register_slot decorators run (C10/C11 append)
STEP_MODULES: list[str] = [
    "nifty.engines.balu.session",
    "nifty.engines.balu.levels",
    "nifty.engines.balu.golden",
    "nifty.engines.balu.moving_line",
    "nifty.engines.balu.zones",  # C10: steps 7-12
    "nifty.engines.balu.keylevels",
    "nifty.engines.balu.location",
    "nifty.engines.balu.pressure",
    "nifty.engines.balu.sweeps",
]


def step(n: int) -> Callable[[Step], Step]:
    if not 1 <= n <= len(STEP_NAMES):
        raise ValueError(f"step slot {n} is outside 1..{len(STEP_NAMES)}")

    def deco(fn: Step) -> Step:
        if n in STEPS and STEPS[n] is not fn:
            raise ValueError(f"step slot {n} ({STEP_NAMES[n - 1]}) is already taken")
        STEPS[n] = fn
        return fn

    return deco


def provisional(fn: Callable[[Any, Bar], EngineOutput]) -> Callable[[Any, Bar], EngineOutput]:
    PROVISIONAL.append(fn)
    return fn


def register_slot(
    name: str,
) -> Callable[[Callable[["BaluParams"], Slot]], Callable[["BaluParams"], Slot]]:
    def deco(f: Callable[["BaluParams"], Slot]) -> Callable[["BaluParams"], Slot]:
        SLOT_FACTORIES[name] = f
        return f

    return deco
