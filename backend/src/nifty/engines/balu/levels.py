"""Steps 2 and 3 (L210-307): chart-timeframe and HTF swings, and the level pool."""

from typing import Any

from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.session import Core, or_bars
from nifty.engines.balu.steps import BarFrame, register_slot, step
from nifty.engines.context import ConfigError
from nifty.engines.pinekit import NaN, PivotHigh, PivotLow

POOL_CAP = 60


def htf_resolution(p: BaluParams, tf_min: float) -> str:
    """Pine `htfRes` (L216-217) in our timeframe names."""
    auto = (
        "15m"
        if tf_min <= 3
        else "30m"
        if tf_min <= 5
        else "1h"
        if tf_min <= 15
        else "4h"
        if tf_min <= 60
        else "1d"
    )
    return {"15m": "15m", "30m": "30m", "1H": "1h", "2H": "2h", "4H": "4h", "Daily": "1d"}.get(
        p.htf_mode, auto
    )


def res_minutes(res: str) -> int:
    return 375 if res == "1d" else {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}[res]


class LevelPool:
    """Parallel arrays of (price, is_high) with merge-average dedupe, prune and a 60-level cap."""

    def __init__(self) -> None:
        self.prices: list[float] = []
        self.is_high: list[bool] = []

    def __len__(self) -> int:
        return len(self.prices)

    def add_level(self, p: float, is_high: bool, atr: float, dedupe_atr: float) -> None:
        """f_addLevel L232: merge into the FIRST same-flag level within atr*dedupe, else append."""
        if p != p or p <= 0 or atr != atr or atr <= 0:
            return
        tol = atr * dedupe_atr
        for i, (v, h) in enumerate(zip(self.prices, self.is_high, strict=True)):
            if h == is_high and abs(v - p) <= tol:
                self.prices[i] = (v + p) / 2.0
                return
        self.prices.append(p)
        self.is_high.append(is_high)

    def prune(self, close: float, atr: float, prune_atr: float) -> None:
        """f_prunePool L247: remove far levels scanning from the END, cap at 60 (drop oldest)."""
        if self.prices and atr == atr and atr > 0:
            far = atr * prune_atr
            for i in range(len(self.prices) - 1, -1, -1):
                if abs(self.prices[i] - close) > far:
                    del self.prices[i]
                    del self.is_high[i]
        while len(self.prices) > POOL_CAP:
            del self.prices[0]
            del self.is_high[0]

    def nearest_above(self, ref: float, gap: float, used: list[float], space: float) -> float:
        """f_nearestAbove L276: lowest level v > ref+gap with no `used` price within `space`."""
        best = NaN
        for v in self.prices:
            if (
                v > ref + gap
                and (best != best or v < best)
                and not any(abs(u - v) <= space for u in used)
            ):
                best = v
        return best

    def nearest_below(self, ref: float, gap: float, used: list[float], space: float) -> float:
        """f_nearestBelow L292: highest level v < ref-gap, same rule. Flags are ignored."""
        best = NaN
        for v in self.prices:
            if (
                v < ref - gap
                and (best != best or v > best)
                and not any(abs(u - v) <= space for u in used)
            ):
                best = v
        return best

    def state(self) -> dict[str, Any]:
        return {"prices": list(self.prices), "is_high": list(self.is_high)}

    def load(self, st: dict[str, Any]) -> None:
        self.prices, self.is_high = list(st["prices"]), list(st["is_high"])


class Swings:
    """chart-timeframe swing pivots (sPH/sPL) and the HTF pivot detectors."""

    def __init__(self, p: BaluParams) -> None:
        self.sph = PivotHigh(p.swing_len, p.swing_len, p.pivot_ties)
        self.spl = PivotLow(p.swing_len, p.swing_len, p.pivot_ties)
        self.hph = PivotHigh(p.htf_pivot_len, p.htf_pivot_len, p.pivot_ties)
        self.hpl = PivotLow(p.htf_pivot_len, p.htf_pivot_len, p.pivot_ties)

    def state(self) -> dict[str, Any]:
        return {k: getattr(self, k).state() for k in ("sph", "spl", "hph", "hpl")}

    def load(self, st: dict[str, Any]) -> None:
        for k in ("sph", "spl", "hph", "hpl"):
            getattr(self, k).load(st[k])


@register_slot("pool")
def make_pool(p: BaluParams) -> LevelPool:
    return LevelPool()


@register_slot("swings")
def make_swings(p: BaluParams) -> Swings:
    return Swings(p)


@step(2)
def pivots_htf(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    sw: Swings = eng.slots["swings"]
    core: Core = eng.slots["core"]
    f.s_ph = sw.sph.update(f.bar.high)
    f.s_pl = sw.spl.update(f.bar.low)
    if not p.use_htf_levels:
        return
    res = htf_resolution(p, eng.tf_min)
    if core.s.n_bars == 1 and res_minutes(res) <= eng.tf_min:
        raise ConfigError(
            "HTF_NOT_HIGHER: HTF Source must be strictly higher than the chart timeframe"
        )
    st = eng.ctx.htf(f.bar, res)
    f.htf_new_bar = st.new_bar
    if st.completed is not None:  # pivothigh(L, L)[1] on the previous COMPLETED HTF bar
        f.htf_ph = sw.hph.update(st.completed.high)
        f.htf_pl = sw.hpl.update(st.completed.low)


@step(3)
def pool_adds(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    pool: LevelPool = eng.slots["pool"]
    s = eng.slots["core"].s

    def add(v: float, h: bool) -> None:
        pool.add_level(v, h, f.atr, p.dedupe_atr)

    add(f.s_ph, True)
    add(f.s_pl, False)
    if p.use_htf_levels and f.htf_new_bar:
        add(f.htf_ph, True)
        add(f.htf_pl, False)
    if f.new_session:
        add(f.pd_h, True)
        add(f.pd_l, False)
        add(f.pd_c, True)  # the prior close is added as BOTH flags so it never merges with itself
        add(f.pd_c, False)
    if s.day_len == or_bars(p, eng.tf_min) + 1:
        add(s.or_high, True)
        add(s.or_low, False)
    pool.prune(f.bar.close, f.atr, p.prune_atr)
    f.out.plots["pool_size"] = float(len(pool))
