"""The three named baselines (spec/07). No extra filters: a new condition is a new named variant.

`anchor_cross_ema_order` is OUR interpretation of the prompt's under-defined crossover (logged in
STATE Open issues): the completed close crosses the session anchor (prev close <= prev V and
close > V for bull; mirrored) while EMA9 is above (bull) / below (bear) EMA21."""

from nifty.engines.research.features import Features


def anchor_cross_ema_order(x: Features) -> int:
    if x.prev_p != x.prev_p or x.prev_v != x.prev_v or x.v != x.v:
        return 0
    if x.prev_p <= x.prev_v and x.p > x.v and x.f > x.s:
        return 1
    if x.prev_p >= x.prev_v and x.p < x.v and x.f < x.s:
        return -1
    return 0


def ema_gap_reexpansion(x: Features) -> int:
    if x.gap_rate > 0 and x.prev_gap_rate <= 0 and x.p > x.f:
        return 1
    if x.gap_rate < 0 and x.prev_gap_rate >= 0 and x.p < x.f:
        return -1
    return 0


def ema_aligned_gap_reexpansion(x: Features) -> int:
    side = ema_gap_reexpansion(x)
    return side if (side == 1 and x.f > x.s) or (side == -1 and x.f < x.s) else 0


BASELINES = {
    "anchor_cross_ema_order": anchor_cross_ema_order,
    "ema_gap_reexpansion": ema_gap_reexpansion,
    "ema_aligned_gap_reexpansion": ema_aligned_gap_reexpansion,
}
