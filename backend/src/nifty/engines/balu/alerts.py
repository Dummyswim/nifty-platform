"""Step 15 (L885-895): bar-close alerts. Regime flips are NOT session-aware (the per-session goldState
reset makes them fire again each session: replicated); there is no flip on the first bar."""

from typing import Any

from nifty.contracts import Ev
from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.steps import BarFrame, register_slot, step


class Alerts:
    def __init__(self) -> None:
        self.prev_regime: int | None = None  # regimeIdx[1]

    def state(self) -> dict[str, Any]:
        return {"prev_regime": self.prev_regime}

    def load(self, st: dict[str, Any]) -> None:
        self.prev_regime = st["prev_regime"]


@register_slot("alerts")
def make_alerts(p: BaluParams) -> Alerts:
    return Alerts()


@step(15)
def alerts(eng: Any, f: BarFrame) -> None:
    a: Alerts = eng.slots["alerts"]
    prev, now = a.prev_regime, f.regime_idx
    if prev is not None and now == 2 and prev != 2:
        f.out.events.append(
            Ev("alert", {"kind": "regime_bull", "name": "Regime Turned Bullish"}, "close")
        )
    if prev is not None and now == 0 and prev != 0:
        f.out.events.append(
            Ev("alert", {"kind": "regime_bear", "name": "Regime Turned Bearish"}, "close")
        )
    if f.bear_div:
        f.out.events.append(
            Ev("alert", {"kind": "divergence_bear", "name": "Bearish Divergence"}, "close")
        )
    if f.bull_div:
        f.out.events.append(
            Ev("alert", {"kind": "divergence_bull", "name": "Bullish Divergence"}, "close")
        )
    a.prev_regime = now
