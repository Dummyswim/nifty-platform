"""Barrier resolution shared by research and the bracket logic (spec/03). Pure.

Per bar, in this order: (1) a gap through a barrier at the open, (2) both barriers inside the
bar (tv: decided by the assumed path O->H->L->C when (high-open) < (open-low), else O->L->H->C;
conservative: STOP + `ambiguous_bar`), (3) a single barrier, (4) nothing.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

Mode = Literal["tv", "conservative"]
Side = Literal["long", "short"]


class BarLike(Protocol):
    @property
    def open(self) -> float: ...
    @property
    def high(self) -> float: ...
    @property
    def low(self) -> float: ...
    @property
    def close(self) -> float: ...


@dataclass(frozen=True)
class Resolution:
    exit_idx: int
    exit_px: float
    reason: str  # TARGET | STOP | TIME
    flags: tuple[str, ...]
    mae_pts: float
    mfe_pts: float
    bars_held: int
    gross_pts: float = 0.0
    cost_pts: float = 0.0
    net_pts: float = 0.0


@dataclass
class BarOutcome:
    reason: str | None
    px: float
    mae: float  # adverse excursion on this bar (points, >= 0), clipped at the exit price
    mfe: float
    flags: list[str] = field(default_factory=list)


def step_bar(
    side: Side,
    entry_px: float,
    stop_px: float | None,
    target_px: float | None,
    bar: BarLike,
    mode: Mode,
) -> BarOutcome:
    s = 1.0 if side == "long" else -1.0
    o, h, lo, c = bar.open, bar.high, bar.low, bar.close
    worst, best = (lo, h) if side == "long" else (h, lo)
    adv_full = max(0.0, s * (entry_px - worst))
    fav_full = max(0.0, s * (best - entry_px))

    def adv(x: float) -> float:
        return max(0.0, s * (entry_px - x))

    def fav(x: float) -> float:
        return max(0.0, s * (x - entry_px))

    stop_gap = stop_px is not None and s * (o - stop_px) <= 0
    tgt_gap = target_px is not None and s * (o - target_px) >= 0
    if stop_gap:
        assert stop_px is not None
        return BarOutcome("STOP", o, adv(o), 0.0, ["gap_through_stop"])
    if tgt_gap:
        assert target_px is not None
        px = o if mode == "tv" else target_px
        return BarOutcome("TARGET", px, 0.0, fav(px), ["gap_through_target"])

    stop_hit = stop_px is not None and s * (worst - stop_px) <= 0
    tgt_hit = target_px is not None and s * (best - target_px) >= 0
    flags: list[str] = []
    # first extreme reached on the assumed path: 'H' or 'L'
    first = "H" if (h - o) < (o - lo) else "L"
    fav_first = first == ("H" if side == "long" else "L")
    if (h - o) == (o - lo) and (stop_hit or tgt_hit):
        flags.append("uncertain_path")

    if stop_hit and tgt_hit:
        assert stop_px is not None and target_px is not None
        if mode == "conservative":
            return BarOutcome("STOP", stop_px, adv(stop_px), 0.0, [*flags, "ambiguous_bar"])
        if fav_first:
            return BarOutcome("TARGET", target_px, 0.0, fav(target_px), flags)
        return BarOutcome("STOP", stop_px, adv(stop_px), 0.0, flags)
    if stop_hit:
        assert stop_px is not None
        mfe = fav_full if mode == "tv" and fav_first else 0.0
        return BarOutcome("STOP", stop_px, adv(stop_px), mfe, flags)
    if tgt_hit:
        assert target_px is not None
        mae = adv_full if mode == "conservative" or not fav_first else 0.0
        return BarOutcome("TARGET", target_px, mae, fav(target_px), flags)
    return BarOutcome(None, c, adv_full, fav_full, flags)


def resolve_barriers(
    side: Side,
    entry_px: float,
    stop_px: float | None,
    target_px: float | None,
    bars: Sequence[BarLike],
    max_hold_bars: int | None,
    mode: Mode,
    cost_pts: float = 0.0,
) -> Resolution:
    """`bars[0]` is the entry bar (entry at its open). `max_hold_bars` counts from it inclusive.

    If the data ends first the result is TIME at the last close with flag `data_ended`.
    `cost_pts` is the explicit round-trip cost (conservative mode); gross/cost/net are reported.
    """
    if not bars:
        raise ValueError("bars must contain at least the entry bar")
    s = 1.0 if side == "long" else -1.0
    mae = mfe = 0.0
    for i, bar in enumerate(bars):
        out = step_bar(side, entry_px, stop_px, target_px, bar, mode)
        mae, mfe = max(mae, out.mae), max(mfe, out.mfe)
        reason, px, flags = out.reason, out.px, list(out.flags)
        if reason is None and max_hold_bars is not None and i + 1 >= max_hold_bars:
            reason = "TIME"
        elif reason is None and i == len(bars) - 1:
            reason, flags = "TIME", [*flags, "data_ended"]
        if reason is not None:
            gross = s * (px - entry_px)
            return Resolution(
                i, px, reason, tuple(flags), mae, mfe, i + 1, gross, cost_pts, gross - cost_pts
            )
    raise AssertionError("unreachable")
