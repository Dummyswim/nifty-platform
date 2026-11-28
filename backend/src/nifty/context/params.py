from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

Writing = Literal["iv", "oi"]  # OI up with IV not rising / raw OI change


# Per-rule (w_min, w_exit) defaults (user-confirmed 2026-11-27) when the caller omits them.
RULE_THRESHOLDS: dict[str, tuple[float, float]] = {"iv": (0.5, 0.3), "oi": (0.25, 0.15)}


class ContextParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    band_pct: float = 10
    band_floor: float = 1.0
    exit_pct: float = 13
    vix_pct: float = 70
    vix_exit_pct: float = 65
    strikes: int = 3
    w_min: float = 0.5
    w_exit: float = 0.3
    roll_oppose: float = 0.5
    roll_min: int = 15
    confirm: int = 3
    release: int = 2
    not_before: str = "09:30"
    late_pct: float = 90  # share of the expected move used at which the day counts as late
    writing: Writing = "iv"

    @model_validator(mode="before")
    @classmethod
    def _rule_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("writing", "iv") in RULE_THRESHOLDS:
            w_min, w_exit = RULE_THRESHOLDS[data.get("writing", "iv")]
            if "w_min" in data and "w_exit" not in data:
                w_exit = min(w_exit, data["w_min"])  # keep the pair consistent
            elif "w_exit" in data and "w_min" not in data:
                w_min = max(w_min, data["w_exit"])
            return {"w_min": w_min, "w_exit": w_exit, **data}
        return data

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.band_pct <= 0:
            raise ValueError("band_pct must be > 0")
        if self.exit_pct < self.band_pct:
            raise ValueError("exit_pct must be >= band_pct")
        if self.vix_exit_pct > self.vix_pct:
            raise ValueError("vix_exit_pct must be <= vix_pct")
        if self.w_exit > self.w_min:
            raise ValueError("w_exit must be <= w_min")
        if not 0 < self.roll_oppose <= 1:
            raise ValueError("roll_oppose must be in (0, 1]")
        if not 0 < self.late_pct <= 200:
            raise ValueError("late_pct must be in (0, 200]")
        for name in ("confirm", "release", "roll_min", "strikes"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        try:
            datetime.strptime(self.not_before, "%H:%M")
        except ValueError:
            raise ValueError("not_before must be HH:MM") from None
        return self
