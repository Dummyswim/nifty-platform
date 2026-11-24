"""Research statistics (pure; spec/07 §Statistics and verdict, research prompt §9). Descriptive only:
the verdict may say "edge not established" and never claims proof (D18).

Thresholds below are OUR choice, stored with every run (`THRESHOLDS`):
- chronological split by SESSION: development 50 % / validation 25 % / untouched evaluation 25 %
  (`dev_end = floor(0.5 n + 0.5)`, `val_end = floor(0.75 n + 0.5)`), purge >= max hold across boundaries;
- session-clustered bootstrap, 95 % interval, 2,000 resamples, fixed seed (whole sessions are drawn
  with replacement; trades of a session are never split);
- `candidate` needs: evaluation CI lower bound > 0, validation expectancy > 0 (same sign), every
  leave-one-session-out evaluation expectancy > 0, AND at least 60 sessions in the data;
- fewer than 60 sessions => `inconclusive` ("insufficient sessions"), whatever the numbers say."""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from nifty.contracts import TradeRecord

THRESHOLDS: dict[str, Any] = {
    "split": [0.5, 0.25, 0.25], "min_sessions": 60, "ci": 0.95, "resamples": 2000,
    "bootstrap_unit": "session", "purge": "max hold across split boundaries",
    "candidate_requires": ["eval CI lower > 0", "validation expectancy > 0", "leave-one-session-out > 0 on evaluation", "sessions >= 60"],
}  # fmt: skip
SPLITS = ("dev", "val", "eval")
Verdict = str  # candidate | inconclusive | edge_not_established


def split_sessions(sessions: Sequence[date]) -> dict[date, str]:
    """Chronological split of the (sorted, unique) sessions into dev / val / eval."""
    ss = sorted(set(sessions))
    n = len(ss)
    dev_end, val_end = math.floor(0.5 * n + 0.5), math.floor(0.75 * n + 0.5)
    return {
        s: ("dev" if i < dev_end else "val" if i < val_end else "eval") for i, s in enumerate(ss)
    }


def purge(
    trades: Sequence[TradeRecord], assign: dict[date, str], session_of: Any, boundaries: dict[str, datetime],
    max_hold: timedelta,
) -> tuple[list[TradeRecord], list[TradeRecord]]:  # fmt: skip
    """Drop trades of an earlier split whose holding window (entry .. exit, or entry + max hold) reaches
    the first bar of the NEXT split. `boundaries[split]` = start of the first bar of that split."""
    nxt = {"dev": "val", "val": "eval"}
    kept, dropped = [], []
    for t in trades:
        sp = assign[session_of(t.entry_time)]
        b = boundaries.get(nxt.get(sp, ""))
        if b is not None and max(t.exit_time, t.entry_time + max_hold) >= b:
            dropped.append(t)
        else:
            kept.append(t)
    return kept, dropped


def bootstrap_ci(
    by_session: dict[date, list[float]], seed: int, resamples: int = 2000, ci: float = 0.95,
    return_samples: bool = False,
) -> tuple[float, float, float] | tuple[float, float, float, list[float]]:  # fmt: skip
    """Mean net points per trade with a session-clustered percentile interval. Whole sessions are
    resampled with replacement (a session's trades stay together). NaN interval for no trades."""
    sess = sorted(by_session)
    sums = np.array([sum(by_session[s]) for s in sess], dtype=float)
    cnts = np.array([len(by_session[s]) for s in sess], dtype=float)
    total = cnts.sum()
    if len(sess) == 0 or total == 0:
        nan = math.nan
        return (nan, nan, nan, []) if return_samples else (nan, nan, nan)
    point = float(sums.sum() / total)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sess), size=(resamples, len(sess)))
    c = cnts[idx].sum(axis=1)
    means = np.where(c > 0, sums[idx].sum(axis=1) / np.where(c > 0, c, 1), np.nan)
    means = means[~np.isnan(means)]
    a = (1 - ci) / 2
    lo, hi = (
        (float(np.quantile(means, a)), float(np.quantile(means, 1 - a)))
        if len(means)
        else (math.nan, math.nan)
    )
    return (point, lo, hi, means.tolist()) if return_samples else (point, lo, hi)


def leave_one_out(by_session: dict[date, list[float]]) -> list[tuple[date, float]]:
    """Expectancy (mean net points per trade) with each session removed in turn."""
    out = []
    for s in sorted(by_session):
        rest = [x for k, v in by_session.items() if k != s for x in v]
        out.append((s, sum(rest) / len(rest) if rest else math.nan))
    return out


def outcome_mix(trades: Sequence[TradeRecord]) -> dict[str, int]:
    c = Counter(t.exit_reason for t in trades)
    fl = Counter(f for t in trades for f in t.flags)
    return {
        "n": len(trades), "TARGET_FIRST": c["TARGET_FIRST"], "STOP_FIRST": c["STOP_FIRST"],
        "TIME_EXIT": c["TIME_EXIT"], "ambiguous": fl["ambiguous_bar"],
        "interrupted": fl["session_cut"] + fl["data_gap"],
    }  # fmt: skip


def _grp(trades: Sequence[TradeRecord], session_of: Any) -> dict[date, list[float]]:
    d: dict[date, list[float]] = {}
    for t in trades:
        d.setdefault(session_of(t.entry_time), []).append(t.net_pts)
    return d


def evaluate(
    trades: Sequence[TradeRecord], sessions: Sequence[date], session_of: Any, boundaries: dict[str, datetime],
    max_hold: timedelta, seed: int, resamples: int = 2000,
) -> dict[str, Any]:  # fmt: skip
    """One (variant, experiment): per-split tables, the evaluation interval and leave-one-session-out."""
    assign = split_sessions(sessions)
    kept, dropped = purge(trades, assign, session_of, boundaries, max_hold)
    res: dict[str, Any] = {"n_trades": len(trades), "n_purged": len(dropped), "splits": {}}
    for sp in SPLITS:
        tr = [t for t in kept if assign[session_of(t.entry_time)] == sp]
        g = _grp(tr, session_of)
        point, lo, hi = bootstrap_ci(g, seed, resamples)  # type: ignore[misc]
        res["splits"][sp] = {
            "sessions": sum(1 for v in assign.values() if v == sp), **outcome_mix(tr),
            "expectancy_pts": None if math.isnan(point) else point,
            "ci_lo": None if math.isnan(lo) else lo, "ci_hi": None if math.isnan(hi) else hi,
        }  # fmt: skip
    ev = _grp([t for t in kept if assign[session_of(t.entry_time)] == "eval"], session_of)
    loso = [m for _, m in leave_one_out(ev)] if len(ev) > 1 else []
    res["loso_min_eval"] = min(loso) if loso else None
    res["loso_n"] = len(loso)
    return res


@dataclass
class Condition:
    name: str
    passed: bool
    detail: str


def verdict(ev: dict[str, Any], n_sessions: int) -> dict[str, Any]:
    """Verdict for one (variant, experiment) from `evaluate` output. Lists every condition."""
    e, v = ev["splits"]["eval"], ev["splits"]["val"]
    lo, val_exp, loso = e["ci_lo"], v["expectancy_pts"], ev["loso_min_eval"]
    conds = [
        Condition("evaluation CI lower bound > 0", lo is not None and lo > 0, f"lower bound {_f(lo)} pts"),
        Condition("validation expectancy agrees in sign (> 0)", val_exp is not None and val_exp > 0, f"validation {_f(val_exp)} pts"),
        Condition("survives leave-one-session-out on evaluation", loso is not None and loso > 0, f"worst {_f(loso)} pts over {ev['loso_n']} sessions"),
        Condition(f"at least {THRESHOLDS['min_sessions']} sessions", n_sessions >= THRESHOLDS["min_sessions"], f"{n_sessions} sessions"),
    ]  # fmt: skip
    if n_sessions < THRESHOLDS["min_sessions"]:
        label, why = "inconclusive", "insufficient sessions"
    elif all(c.passed for c in conds):
        label, why = "candidate", "all conditions passed; a candidate is not proof of an edge"
    else:
        label, why = "edge_not_established", "at least one condition failed"
    return {"verdict": label, "reason": why, "conditions": [c.__dict__ for c in conds]}


def run_verdict(per_variant: Sequence[dict[str, Any]], n_sessions: int) -> dict[str, Any]:
    """Run level: `candidate` if any variant is one (with the multiple-testing caveat), else
    `inconclusive` below 60 sessions, else `edge_not_established`."""
    labels = [p["verdict"]["verdict"] for p in per_variant]
    if "candidate" in labels:
        top, why = (
            "candidate",
            f"{labels.count('candidate')} of {len(labels)} variants passed; {len(labels)} variants were tested (multiple comparisons)",
        )
    elif n_sessions < THRESHOLDS["min_sessions"]:
        top, why = (
            "inconclusive",
            f"insufficient sessions ({n_sessions} < {THRESHOLDS['min_sessions']})",
        )
    else:
        top, why = "edge_not_established", "no variant passed every condition"
    return {
        "verdict": top,
        "reason": why,
        "status": "experimental",
        "n_variants_tested": len(labels),
    }


def _f(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"
