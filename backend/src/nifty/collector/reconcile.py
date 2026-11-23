"""EOD reconcile (pure): compare the day's historical 1m candles with what the collector stored.
Differences become `revision+1` rows flagged `reconciled`; identical bars write nothing (the upsert
rule treats an identical row as a no-op anyway)."""

from collections.abc import Sequence

from nifty.contracts import Bar


def _same(a: Bar, b: Bar) -> bool:
    return (a.open, a.high, a.low, a.close, a.volume, a.volume_kind) == (
        b.open, b.high, b.low, b.close, b.volume, b.volume_kind,
    )  # fmt: skip


def plan_reconcile(stored: Sequence[Bar], fetched: Sequence[Bar]) -> list[Bar]:
    """Bars to upsert: fetched bars that differ from the stored latest revision (or are missing)."""
    have = {b.bar_start_utc: b for b in stored}
    out = []
    for f in sorted(fetched, key=lambda b: b.bar_start_utc):
        cur = have.get(f.bar_start_utc)
        if cur is None or not _same(cur, f):
            flags = tuple(dict.fromkeys([*f.quality_flags, "reconciled"]))
            out.append(f.model_copy(update={"quality_flags": flags}))
    return out
