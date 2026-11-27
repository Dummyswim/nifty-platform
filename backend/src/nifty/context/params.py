from pydantic import BaseModel, ConfigDict


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
