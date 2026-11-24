"""Params of `research.distance_entry_v1`: the reference config (spec/07) plus the armed-resumption knobs."""

from typing import Literal

from pydantic import Field

from nifty.contracts import EngineParams, UiParams

Baseline = Literal[
    "anchor_cross_ema_order",
    "ema_gap_reexpansion",
    "ema_aligned_gap_reexpansion",
    "armed_resumption",
]


class ResearchUi(UiParams):
    show_ema: bool = True
    show_anchor: bool = True
    color_ema_fast: str = "#4c8dff"
    color_ema_slow: str = "#9c6ade"
    color_anchor: str = "#ffa726"


class ResearchParams(EngineParams):
    baseline: Baseline = "ema_gap_reexpansion"
    # reference config: targets 10 / 20 are SEPARATE experiments (run with different params)
    target_pts: float = Field(10.0, gt=0)
    stop_pts: float = Field(12.0, gt=0)
    max_hold_bars: int = Field(10, ge=1)
    entry_start_hm: int = Field(930, ge=915, le=1530)
    entry_end_hm: int = Field(1445, ge=915, le=1530)
    cost_pts: float = Field(0.0, ge=0)  # explicit round-trip cost, applied to every trade (shown)
    # features
    ema_fast: int = Field(9, ge=1)
    ema_slow: int = Field(21, ge=2)
    atr_len: int = Field(14, ge=2)
    rate_k: int = Field(3, ge=1)
    ema_seed: Literal["first", "sma"] = "first"
    anchor_proxy: bool = (
        False  # weight spot by the runner's proxy (futures) volume when it has none
    )
    # armed resumption (docs/engines/research-armed.md)
    trigger_mode: Literal["close", "intrabar"] = "close"
    pullback_min: int = Field(2, ge=1)
    pullback_max: int = Field(5, ge=1)
    arm_expiry_bars: int = Field(5, ge=1)
    max_rearms: int = Field(1, ge=0)
    ui: ResearchUi = Field(default_factory=ResearchUi)
