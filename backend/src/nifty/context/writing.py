"""Option-writing classification: OI up with premium down is writing."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Leg:
    is_call: bool
    oi: float
    prem: float
    oi_base: float
    prem_base: float


def writing_qty(leg: Leg) -> float:
    d_oi = leg.oi - leg.oi_base
    return d_oi if d_oi > 0 and leg.prem < leg.prem_base else 0.0


def score(legs: Sequence[Leg]) -> float:
    """(PW - CW) / (PW + CW): +1 all put writing, -1 all call writing, 0.0 when none."""
    cw = sum(writing_qty(x) for x in legs if x.is_call)
    pw = sum(writing_qty(x) for x in legs if not x.is_call)
    total = cw + pw
    return (pw - cw) / total if total else 0.0


def raw_oi(legs: Sequence[Leg]) -> tuple[float, float]:
    """(sum dOI calls, sum dOI puts) with no price filter."""
    calls = sum(x.oi - x.oi_base for x in legs if x.is_call)
    puts = sum(x.oi - x.oi_base for x in legs if not x.is_call)
    return calls, puts


def one_sided(w_day: float, w_roll: float, w_min: float) -> int:
    """-1/0/+1 when |w_day| >= w_min and the rolling score is zero or agrees in sign."""
    if abs(w_day) < w_min:
        return 0
    sign = 1 if w_day > 0 else -1
    if w_roll == 0 or (w_roll > 0) == (w_day > 0):
        return sign
    return 0
