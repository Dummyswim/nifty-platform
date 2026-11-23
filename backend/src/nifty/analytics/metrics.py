"""Backtest metrics (pure). Units: index points (`_pts`); `_inr` only for option paper trades.

Definitions (ours, documented in STATE):
- win = net_pts > 0, loss = net_pts < 0; a flat trade is neither and breaks a streak.
- win_rate = wins / n_trades (fraction). expectancy_pts = mean net_pts per trade.
- profit_factor = gross profit / |gross loss|; no losses => null + flag `no_losses`.
- max_drawdown_pts = largest peak-to-trough fall of cumulative net_pts in exit order (peak 0).
- sharpe = mean / sample stdev of per-session net_pts * sqrt(252), rf = 0. Sessions come from
  `sessions` (every session in the tested data, zero-trade sessions count as 0) or, if omitted, from
  the trades' exit sessions. Reported with n_sessions; low_n when n_sessions < 30.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime
from typing import Any, Protocol

LOW_N = 30


class TradeLike(Protocol):
    @property
    def net_pts(self) -> float: ...
    @property
    def exit_time(self) -> datetime: ...


def _streak(flags: Iterable[int], want: int) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f == want else 0
        best = max(best, cur)
    return best


def compute_metrics(
    trades: Sequence[TradeLike],
    session_of: Callable[[datetime], date],
    sessions: Iterable[date] | None = None,
) -> dict[str, Any]:
    ts = sorted(trades, key=lambda t: t.exit_time)
    net = [t.net_pts for t in ts]
    wins, losses = [x for x in net if x > 0], [x for x in net if x < 0]
    flags: list[str] = []
    gp, gl = sum(wins), -sum(losses)
    pf: float | None = None
    if gl > 0:
        pf = gp / gl
    elif ts:
        flags.append("no_losses")
    peak = cum = dd = 0.0
    for x in net:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    per: dict[date, float] = defaultdict(float)
    for s in sessions or []:
        per[s] += 0.0
    for t in ts:
        per[session_of(t.exit_time)] += t.net_pts
    daily = list(per.values())
    sharpe: float | None = None
    if len(daily) >= 2:
        sd = statistics.stdev(daily)
        if sd > 0:
            sharpe = statistics.fmean(daily) / sd * math.sqrt(252)
        else:
            flags.append("zero_variance")
    sign = [1 if x > 0 else -1 if x < 0 else 0 for x in net]
    low_n = len(daily) < LOW_N
    if low_n:
        flags.append("low_n")
    return {
        "n_trades": len(ts),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(ts) if ts else None,
        "gross_profit_pts": gp,
        "gross_loss_pts": -gl,
        "profit_factor": pf,
        "total_pnl_pts": sum(net),
        "expectancy_pts": sum(net) / len(ts) if ts else None,
        "max_drawdown_pts": dd,
        "max_consecutive_wins": _streak(sign, 1),
        "max_consecutive_losses": _streak(sign, -1),
        "sharpe": sharpe,
        "n_sessions": len(daily),
        "low_n": low_n,
        "flags": flags,
    }
