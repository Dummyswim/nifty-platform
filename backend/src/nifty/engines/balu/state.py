"""SessionState: the JSON-serialisable scalar state of the engine (Pine `var`s). Later chunks read
`regime_idx`-driving fields and `flow_*` from here; windows and arrays live in their own slots."""

import math
from dataclasses import asdict, dataclass, fields
from typing import Any

NaN = math.nan


@dataclass
class SessionState:
    n_bars: int = 0  # bars seen (Pine bar_index + 1)
    prev_in_session: bool = False
    prev_day: str | None = None  # session date (ISO) of the previous bar
    # session anchors (L188-209)
    or_high: float = NaN
    or_low: float = NaN
    sess_hi: float = NaN
    sess_lo: float = NaN
    day_len: int = 0
    # golden line (L314-357)
    vol_seen: bool = False
    g_chart_pv: float = 0.0
    g_chart_w: float = 0.0
    g_proxy_pv: float = 0.0
    g_proxy_w: float = 0.0
    g_sum_p: float = 0.0
    g_cnt: int = 0
    gold_state: int = 0
    regime_idx: int = 1  # 2 BULL, 1 NEUTRAL, 0 BEAR
    # moving line (L363-395)
    cvd: float = 0.0
    cvd_hi: float = NaN
    cvd_lo: float = NaN
    flow_state: int = 0  # 1 RISING, 0 FLAT, -1 FALLING
    flow_z: float = 0.0
    flow_ready: bool = False
    # divergence memory (L397-430)
    last_ph: float = NaN
    last_ph_cvd: float = NaN
    last_pl: float = NaN
    last_pl_cvd: float = NaN

    def state(self) -> dict[str, Any]:
        return {
            k: (None if isinstance(v, float) and v != v else v) for k, v in asdict(self).items()
        }

    def load(self, st: dict[str, Any]) -> None:
        for f in fields(self):
            v = st[f.name]
            setattr(self, f.name, NaN if v is None and f.type is float else v)
