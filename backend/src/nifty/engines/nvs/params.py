"""NVS Params: Pine input defaults (reference/pine/Nifty_VWAP_Spread_Scalper.pine L46-110)."""

from typing import Literal

from pydantic import Field

from nifty.contracts import EngineParams, UiParams


class NvsUi(UiParams):
    show_labels: bool = True
    show_exit_labels: bool = True
    show_ema: bool = Field(default=True, title="Show EMA fast / slow")
    show_bands: bool = True
    show_levels: bool = True
    show_table: bool = True
    color_buy: str = "#1b9e4b"
    color_sell: str = "#d03a2f"
    color_vwap: str = "#f59e0b"
    color_ema_fast: str = "#2962ff"  # Pine color.blue
    color_ema_slow: str = "#9c27b0"  # Pine color.purple


class NvsParams(EngineParams):
    # Trend & momentum
    ema_fast_len: int = Field(9, ge=1)
    ema_slow_len: int = Field(21, ge=2)
    use_rsi: bool = True
    rsi_len: int = Field(14, ge=2)
    atr_len: int = Field(14, ge=2)
    rsi_long: float = 60.0
    rsi_short: float = 40.0
    rsi_cross_bars: int = Field(3, ge=1)
    # Spread from VWAP
    min_dev_atr: float = Field(0.25, ge=0.0)
    max_dev_atr: float = Field(1.6, ge=0.1)
    speed_bars: int = Field(3, ge=1)
    min_speed_atr: float = Field(0.35, ge=0.0)
    close_pos_min: float = Field(0.6, ge=0.5, le=1.0)
    chop_bars: int = Field(20, ge=3)
    max_vwap_flips: int = Field(3, ge=0)
    # Risk & targets
    min_risk_atr: float = Field(0.7, ge=0.1)
    max_risk_atr: float = Field(1.8, ge=0.2)
    target_r: float = Field(1.5, ge=0.2)
    be_r: float = Field(1.0, ge=0.2)
    be_offset_r: float = Field(0.05, ge=0.0)
    max_hold_bars: int = Field(15, ge=1)
    # Signal exits
    exit_vwap_buf_atr: float = Field(0.1, ge=0.0)
    ext_atr: float = Field(2.0, ge=0.5)
    rsi_exit: float = 50.0
    # Costs (script math; the emulator commission is `commission_pct`)
    cost_bps: float = Field(2.5, ge=0.0)
    min_tgt_cost_x: float = Field(2.5, ge=0.0)
    commission_pct: float = Field(0.0125, ge=0.0)  # strategy(): percent per side
    # Session & limits (IST HHMM, compared with the bar END)
    entry_start_hm: int = Field(930, ge=915, le=1530)
    entry_end_hm: int = Field(1445, ge=915, le=1530)
    flat_hm: int = Field(1515, ge=915, le=1530)
    warmup_bars: int = Field(30, ge=1)
    min_sess_bars: int = Field(5, ge=1)
    cooldown_bars: int = Field(2, ge=0)
    max_trades_day: int = Field(6, ge=1)
    max_day_loss_r: float = Field(3.0, ge=0.5)
    allow_long: bool = True
    allow_short: bool = True
    # Port-only
    anchor_mode: Literal["signal_close", "fill_price"] = "signal_close"
    ema_seed: Literal["first", "sma"] = "first"
    ui: NvsUi = Field(default_factory=NvsUi)
