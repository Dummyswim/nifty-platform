from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

Writing = Literal["iv", "oi"]  # OI up with IV not rising / raw OI change


class ContextParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    band_pct: float = 10
    band_floor: float = 1.0
    exit_pct: float = 13
    vix_pct: float = 70
    vix_exit_pct: float = 65
    strikes: int = 3
    w_min: float = 0.3
    w_exit: float = 0.15
    roll_min: int = 15
    confirm: int = 3
    release: int = 2
    not_before: str = "09:30"
    writing: Writing = "iv"

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
        for name in ("confirm", "release", "roll_min", "strikes"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        try:
            datetime.strptime(self.not_before, "%H:%M")
        except ValueError:
            raise ValueError("not_before must be HH:MM") from None
        return self
