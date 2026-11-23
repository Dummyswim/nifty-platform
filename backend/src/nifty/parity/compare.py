"""Tier A/B/C comparators (D16). Pure: take engine outputs and reference data, return numbers."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from nifty.contracts import TradeRecord
from nifty.parity.tv_io import RefTrade
from nifty.timeutil import to_ist

CLOSE_FILLS = {"EOD", "SESSION_END"}  # filled at the bar close, stamped with the bar END


@dataclass
class TierA:
    series: dict[str, tuple[float, int]] = field(default_factory=dict)  # name -> (max_abs, n)
    diffs: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(m <= 1e-6 for m, _ in self.series.values()) and not self.diffs


def tier_a(
    ours: Sequence[tuple[datetime, dict[str, float | None]]],
    golden: dict[str, dict[datetime, float]],
    warmup: int,
    tol: float = 1e-6,
) -> TierA:
    """`golden[series][bar_start]` vs our plots after `warmup` bars; None must match NaN."""
    res = TierA()
    for name, g in golden.items():
        worst, n = 0.0, 0
        for i, (ts, plots) in enumerate(ours):
            if i < warmup or ts not in g:
                continue
            a, b = plots.get(name), g[ts]
            a_na, b_na = a is None, b != b
            if a_na != b_na:
                if len(res.diffs) < 5:
                    res.diffs.append(f"{name} {to_ist(ts):%m-%d %H:%M} ours={a} tv={b}")
                continue
            if a is not None:
                worst, n = max(worst, abs(a - b)), n + 1
        res.series[name] = (worst, n)
    return res


@dataclass
class TierBC:
    n_ours: int
    n_ref: int
    entries_ok: int = 0
    exits_ok: int = 0
    diffs: list[str] = field(default_factory=list)


def exit_bar_start(t: TradeRecord, tf: timedelta) -> datetime:
    return t.exit_time - tf if t.exit_reason in CLOSE_FILLS else t.exit_time


def ref_exit_bar_start(t: RefTrade, tf: timedelta) -> datetime:
    return t.exit_time  # both sources report the bar start (see load_oracle_trades)


def tier_bc(
    ours: Sequence[TradeRecord],
    ref: Sequence[RefTrade],
    tf: timedelta = timedelta(minutes=5),
    px_tol: float = 0.01,
    exit_px_tol: float | None = None,
) -> TierBC:
    """Tier B (entries: same fill bar, side, price) and C (exits: same bar and reason).
    `exit_px_tol` set => exit prices must also agree (TradingView golden)."""
    res = TierBC(len(ours), len(ref))
    mine: dict[tuple[datetime, str], TradeRecord] = {(t.entry_time, t.side): t for t in ours}
    for r in ref:
        t = mine.get((r.entry_time, r.side))
        tag = f"{to_ist(r.entry_time):%m-%d %H:%M} {r.side}"
        if t is None:
            res.diffs.append(f"entry missing: {tag} @ {r.entry_px}")
            continue
        if abs(t.entry_px - r.entry_px) > px_tol:
            res.diffs.append(f"entry px {tag}: ours {t.entry_px} ref {r.entry_px}")
            continue
        res.entries_ok += 1
        same_bar = exit_bar_start(t, tf) == ref_exit_bar_start(r, tf)
        same_px = exit_px_tol is None or abs(t.exit_px - r.exit_px) <= exit_px_tol
        if same_bar and t.exit_reason == r.reason and same_px:
            res.exits_ok += 1
        else:
            res.diffs.append(
                f"exit {tag}: ours {to_ist(exit_bar_start(t, tf)):%m-%d %H:%M} "
                f"{t.exit_reason} @ {t.exit_px:.2f} | ref {to_ist(r.exit_time):%m-%d %H:%M} "
                f"{r.reason} @ {r.exit_px:.2f}"
            )
    ref_keys = {(r.entry_time, r.side) for r in ref}
    for k, t in mine.items():
        if k not in ref_keys:
            res.diffs.append(f"extra entry: {to_ist(t.entry_time):%m-%d %H:%M} {t.side}")
    return res
