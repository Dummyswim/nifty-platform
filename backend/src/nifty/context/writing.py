"""Option-writing scores. `iv` rule: OI up with that leg's IV not rising is writing.
`oi` rule: raw OI change per side, no filter (the reel's method)."""

from collections.abc import Sequence
from dataclasses import dataclass

IV_TOL = 0.05  # vol pts: an IV rise up to this much still counts as "not rising"


@dataclass(frozen=True)
class Leg:
    is_call: bool
    oi: float
    oi_base: float
    iv: float | None  # vol points; None when the IV could not be computed
    iv_base: float | None


def writing_qty_iv(leg: Leg) -> float:
    d_oi = leg.oi - leg.oi_base
    if d_oi <= 0 or leg.iv is None or leg.iv_base is None:
        return 0.0
    return d_oi if leg.iv <= leg.iv_base + IV_TOL else 0.0


def score_iv(legs: Sequence[Leg]) -> float:
    """(PW - CW) / (PW + CW): +1 all put writing, -1 all call writing, 0.0 when none."""
    cw = sum(writing_qty_iv(x) for x in legs if x.is_call)
    pw = sum(writing_qty_iv(x) for x in legs if not x.is_call)
    total = cw + pw
    return (pw - cw) / total if total else 0.0


def score_oi(legs: Sequence[Leg]) -> float:
    """(dOI_PE - dOI_CE) / (|dOI_PE| + |dOI_CE|), 0.0 when both are 0."""
    calls, puts = raw_oi(legs)
    total = abs(puts) + abs(calls)
    return (puts - calls) / total if total else 0.0


def raw_oi(legs: Sequence[Leg]) -> tuple[float, float]:
    """(sum dOI calls, sum dOI puts) with no filter."""
    calls = sum(x.oi - x.oi_base for x in legs if x.is_call)
    puts = sum(x.oi - x.oi_base for x in legs if not x.is_call)
    return calls, puts


def one_sided(w_day: float, w_roll: float, w_min: float, roll_oppose: float = 0.5) -> int:
    """-1/0/+1 when |w_day| >= w_min and the rolling score does not oppose strongly
    (opposite sign with |w_roll| > roll_oppose)."""
    if abs(w_day) < w_min:
        return 0
    if w_roll * w_day < 0 and abs(w_roll) > roll_oppose:
        return 0
    return 1 if w_day > 0 else -1
