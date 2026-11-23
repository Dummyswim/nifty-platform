"""Balu Zone Scalper v2 Params: every `input.*` of Pine L74-164 with default, bounds and group.

Pure drawing options (show* for zones/labels/gold/CVD/panel, colours, tint, panel position) live in
`ui` (excluded from config_hash); toggles that gate a computed event or alert stay here."""

import re
from typing import Literal

from pydantic import Field, field_validator

from nifty.contracts import EngineParams, UiParams


class BaluUi(UiParams):
    show_zones: bool = True
    show_zone_lbl: bool = True
    show_gold: bool = True
    gold_tint: bool = False
    show_cvd: bool = True
    show_panel: bool = True
    panel_pos: Literal[
        "Top Left", "Top Center", "Top Right", "Bottom Left", "Bottom Center", "Bottom Right"
    ] = "Top Right"
    color_supply: str = "#ef5350"
    color_demand: str = "#26a69a"
    color_gold: str = "#ffa726"
    color_cvd_up: str = "#26c281"
    color_cvd_dn: str = "#e74c3c"
    color_neutral: str = "#9e9e9e"
    color_kl_or: str = "#ff9800"
    color_kl_hl: str = "#00bcd4"
    color_kl_piv: str = "#7e57c2"


HtfMode = Literal["Auto", "15m", "30m", "1H", "2H", "4H", "Daily"]


class BaluParams(EngineParams):
    # 1) Zone Map
    session_str: str = Field("0915-1530", pattern=r"^\d{4}-\d{4}$")
    swing_len: int = Field(3, ge=1, le=10)
    zone_tiers: int = Field(2, ge=1, le=4)
    zone_thick_atr: float = Field(0.35, ge=0.05, le=2.0)
    cap_base_atr: float = Field(2.5, ge=0.5, le=20.0)
    cap_step_atr: float = Field(2.5, ge=0.5, le=20.0)
    or_minutes: int = Field(15, ge=1, le=120)
    dedupe_atr: float = Field(0.50, ge=0.05, le=3.0)
    min_space_atr: float = Field(1.0, ge=0.0, le=5.0)
    prune_atr: float = Field(14.0, ge=3.0, le=60.0)
    keep_mitigated: bool = False
    # 2) Higher-timeframe context
    use_htf_levels: bool = True
    htf_mode: HtfMode = "Auto"
    htf_pivot_len: int = Field(2, ge=1, le=10)
    # 3) Golden Line
    gold_source: Literal["VWAP (session)", "Daily Pivot (PP)", "EMA"] = "VWAP (session)"
    gold_ema_len: int = Field(50, ge=5, le=400)
    gold_dead_atr: float = Field(0.25, ge=0.0, le=2.0)
    gold_proxy: bool = False
    proxy_volume_instrument: str | None = None  # front-month future from the Kite master (D10)
    # 4) Moving Line
    cvd_source: Literal["Auto", "Real Volume", "Price Action"] = "Auto"
    flow_warm_bars: int = Field(10, ge=2, le=120)
    flow_smooth_len: int = Field(5, ge=1, le=50)
    flow_slope_len: int = Field(5, ge=1, le=50)
    flow_dead: float = Field(0.30, ge=0.0, le=2.0)
    show_div: bool = True
    div_pivot_len: int = Field(5, ge=2, le=20)
    # 5) Intrabar pressure (BALU-2)
    show_footprint: bool = True
    fp_ltf: str = "1"
    fp_min_sub_bars: int = Field(3, ge=2, le=60)
    fp_imbal: float = Field(0.50, ge=0.1, le=0.95)
    fp_eff_mult: float = Field(1.3, ge=0.5, le=5.0)
    fp_eff_len: int = Field(20, ge=5, le=100)
    fp_at_zone_only: bool = True
    fp_mark_traps: bool = True
    sweep_conf_only: bool = True
    sweep_conf_bars: int = Field(3, ge=1, le=20)
    # 6) Path history (BALU-3)
    use_prob: bool = True
    prob_horizon: int = Field(20, ge=3, le=200)
    prob_min_n: int = Field(100, ge=5, le=1000)
    # 7) Key levels
    show_key_levels: bool = True
    kl_pdhl: bool = True
    kl_pdc: bool = True
    kl_pivot: bool = False
    kl_or: bool = True
    # 8) Panel
    zone_prox_atr: float = Field(0.35, ge=0.05, le=2.0)
    # port-only (the golden decides)
    ema_seed: Literal["first", "sma"] = "first"
    pivot_ties: Literal["default", "strict"] = "default"
    ui: BaluUi = Field(default_factory=BaluUi)

    @field_validator("session_str")
    @classmethod
    def _session_ok(cls, v: str) -> str:
        a, b = session_minutes(v)
        if not (0 <= a < b <= 24 * 60):
            raise ValueError("session must be HHMM-HHMM with start < end")
        return v


def session_minutes(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{2})(\d{2})-(\d{2})(\d{2})", s)
    if m is None:
        raise ValueError("session must look like 0915-1530")
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    return h1 * 60 + m1, h2 * 60 + m2
