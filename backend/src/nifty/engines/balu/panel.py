"""Step 14 (L847-884): the 13-row panel. `panel()` shows the LATEST confirmed bar (not replayed)."""

import math
from typing import Any

from nifty.engines.balu.params import BaluParams
from nifty.engines.balu.steps import BarFrame, panel_builder, register_slot, step


def r_half_up(x: float, nd: int = 0) -> float:
    return float(math.floor(x * 10**nd + 0.5) / 10**nd)


def _n(x: float) -> float | None:
    return None if x != x else x


class PanelState:
    def __init__(self) -> None:
        self.raw: dict[str, Any] | None = None

    def state(self) -> dict[str, Any]:
        return {"raw": self.raw}

    def load(self, st: dict[str, Any]) -> None:
        self.raw = st["raw"]


@register_slot("panel")
def make_panel(p: BaluParams) -> PanelState:
    return PanelState()


def rows(r: dict[str, Any]) -> list[dict[str, str]]:
    """13 rows {label, value, role} from the raw snapshot values (strings follow Pine L862-883)."""
    reg = {2: ("BULL", "bull"), 1: ("NEUTRAL", "neutral"), 0: ("BEAR", "bear")}[r["regime_idx"]]
    fl = {1: ("RISING", "bull"), 0: ("FLAT", "neutral"), -1: ("FALLING", "bear")}[r["flow_state"]]
    loc = {0: ("AT DEMAND", "demand"), 1: ("MID", "neutral"), 2: ("AT SUPPLY", "supply")}[
        r["loc_idx"]
    ]
    close = r["close"]

    def dist(nxt: float | None, sign: int, proj: bool) -> str:
        if nxt is None:
            return "—"
        return f"{r_half_up(sign * (nxt - close), 1):.1f}" + (" (proj)" if proj else "")

    up = r["use_prob"]
    s = r["stats"]
    prob_ready = up and s["n_finished"] >= r["prob_min_n"]
    n_txt = (
        f"{s['n_finished']} done / {s['n_pending']} open / {s['sample_days']} days" if up else "OFF"
    )
    cnt = (
        " / ".join(str(s[k]) for k in ("n_up", "n_dn", "n_timeout", "n_both", "n_cut"))
        if up
        else "—"
    )
    if not up:
        p_txt = b_txt = "OFF"
    else:
        p_txt = (
            f"{int(r_half_up(s['resolved_share']))}% (n={s['n_resolved']})"
            if prob_ready and s["n_resolved"] >= r["prob_min_n"] and s["resolved_share"] is not None
            else "Too few resolved episodes"
        )
        b_txt = (
            f"{int(r_half_up(s['history_lo']))}..{int(r_half_up(s['history_hi']))}% (not a CI)"
            if prob_ready and s["history_lo"] is not None and s["history_hi"] is not None
            else "Too few finished episodes"
        )
    if not r["fp_valid"]:
        fp = "n/a (LTF unavailable/invalid)"
    elif r["press_buy"]:
        fp = "BUY?" if r.get("provisional") else "BUY"
    elif r["press_sell"]:
        fp = "SELL?" if r.get("provisional") else "SELL"
    else:
        fp = "—"
    div = "BEARISH" if r["bear_div"] else "BULLISH" if r["bull_div"] else "—"
    return [
        {"label": "Regime", "value": reg[0], "role": reg[1]},
        {"label": "Flow (volume proxy)" if r["use_real_vol"] else "Flow (range proxy)", "value": fl[0], "role": fl[1]},
        {"label": "Location", "value": loc[0], "role": loc[1]},
        {"label": "To Supply", "value": dist(r["next_up"], 1, r["next_up_proj"]), "role": "supply"},
        {"label": "To Demand", "value": dist(r["next_dn"], -1, r["next_dn_proj"]), "role": "demand"},
        {"label": "History (closed state)", "value": n_txt, "role": "neutral"},
        {"label": "Up / Dn / Timeout / Both / Cut", "value": cnt, "role": "neutral"},
        {"label": "Up first | resolved only", "value": p_txt, "role": "neutral"},
        {"label": "Up by H | history bounds", "value": b_txt, "role": "neutral"},
        {"label": "Forecast / edge / effective n", "value": "Not established", "role": "neutral"},
        {"label": "Divergence", "value": div, "role": "bear" if r["bear_div"] else "bull" if r["bull_div"] else "neutral"},
        {"label": "Pressure | Gold", "value": f"{fp} | {r['gold_anchor']}",
         "role": "demand" if r["press_buy"] else "supply" if r["press_sell"] else "neutral"},
        {"label": "Sampling", "value": f"Transitions; real zones; H={r['prob_horizon']}", "role": "neutral"},
    ]  # fmt: skip


@step(14)
def panel_snapshot(eng: Any, f: BarFrame) -> None:
    p: BaluParams = eng.p
    loc, fp, st = f.extra["location"], f.extra["fp"], f.extra["stats"]
    s = eng.slots["core"].s
    eng.slots["panel"].raw = {
        "regime_idx": f.regime_idx, "flow_state": f.flow_state, "loc_idx": loc.loc_idx,
        "use_real_vol": p.cvd_source == "Real Volume" or (p.cvd_source == "Auto" and s.vol_seen),
        "close": f.bar.close, "next_up": _n(loc.next_up), "next_dn": _n(loc.next_dn),
        "next_up_proj": loc.next_up_proj, "next_dn_proj": loc.next_dn_proj,
        "use_prob": p.use_prob, "prob_min_n": p.prob_min_n, "prob_horizon": p.prob_horizon,
        "stats": {k: getattr(st, k) for k in st.__dataclass_fields__},
        "bear_div": f.bear_div, "bull_div": f.bull_div, "fp_valid": fp.valid,
        "press_buy": fp.press_buy, "press_sell": fp.press_sell, "gold_anchor": f.gold_anchor,
    }  # fmt: skip


@panel_builder
def build_panel(eng: Any) -> dict[str, Any] | None:
    raw = eng.slots["panel"].raw
    return None if raw is None else {"rows": rows(raw)}
