"""Long-history stability check of one engine on stored 1m bars (read-only).

  python tools/stability_check.py --engine pine.balu_zone --symbol "NIFTY 50" --from 2026-05-04 --to 2026-11-20
  python tools/stability_check.py --engine pine.nvs_scalper ... --tv-trades fixtures/tv_golden/nvs/trades.csv

Checks: batch run (time, memory), incremental == batch, restart at random cuts == batch (D14), plots without
non-finite values after warmup, event/trade counts per type. With --tv-trades also compares trades with a
TradingView "List of trades" export (entries/exits matched within one bar). Descriptive only."""

import argparse
import json
import random
import resource
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from nifty.db.bars import read_bars  # noqa: E402
from nifty.db.instruments import find_instrument  # noqa: E402
from nifty.db.session import get_engine  # noqa: E402
from nifty.engines.base import get_engine as get_spec  # noqa: E402
from nifty.engines.base import load_builtin_engines  # noqa: E402
from nifty.engines.runner import run_batch, run_incremental, run_with_restart  # noqa: E402
from nifty.timeutil import Calendar  # noqa: E402


def view(r):  # type: ignore[no-untyped-def]
    return {"plots": r.plots, "events": r.events, "trades": r.trades, "panel": r.panel, "cfg": r.config_hash}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--symbol", default="NIFTY 50")
    ap.add_argument("--from", dest="d0", type=date.fromisoformat, required=True)
    ap.add_argument("--to", dest="d1", type=date.fromisoformat, required=True)
    ap.add_argument("--tf")
    ap.add_argument("--cuts", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--tv-trades", type=Path)
    ap.add_argument("--params", default="{}", help="engine params as JSON")
    a = ap.parse_args()
    params = json.loads(a.params)
    load_builtin_engines()
    cal = Calendar.load()
    with get_engine().connect() as c:
        ins = find_instrument(c, a.symbol)
        if ins is None:
            print("unknown symbol")
            return 2
        bars = read_bars(c, ins.instrument_id, "1m", cal.session_bounds(a.d0)[0], cal.session_bounds(a.d1)[1])
    tf = a.tf or get_spec(a.engine, allow_unready=True).cls.default_timeframe
    sessions = sorted({cal.session_date(b.bar_start_utc) for b in bars})
    print(f"{a.engine} on {ins.instrument_id}: {len(bars)} 1m bars, {len(sessions)} sessions, tf {tf}")
    kw = {"instrument": ins, "calendar": cal, "source_id": "stability", "allow_unready": True}
    t = time.perf_counter()
    batch = run_batch(a.engine, params, bars, tf, **kw)
    dt = time.perf_counter() - t
    print(f"batch: {len(batch.plots)} chart bars in {dt:.1f}s ({len(batch.plots) / dt:,.0f}/s), peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB")
    vb, ok = view(batch), True
    t = time.perf_counter()
    same = view(run_incremental(a.engine, params, bars, tf, **kw)) == vb
    print(f"incremental == batch: {same} ({time.perf_counter() - t:.1f}s)")
    ok &= same
    rng = random.Random(a.seed)
    for cut in sorted(rng.sample(range(50, len(batch.plots) - 50), a.cuts)):
        same = view(run_with_restart(a.engine, params, bars, tf, cut=cut, **kw)) == vb
        print(f"restart after chart bar {cut} == batch: {same}")
        ok &= same
    warm = get_spec(a.engine, allow_unready=True).cls.warmup_bars
    bad = Counter(k for _, p in batch.plots[warm:] for k, v in p.items() if isinstance(v, float) and v != v or v in (float("inf"), float("-inf")))
    print(f"non-finite plot values after warmup: {dict(bad) or 'none'}")
    print("events:", dict(Counter(e.event_type for e in batch.events)) or "none", "| trades:", len(batch.trades))
    print("overlays:", len(batch.overlays), "| panel:", "yes" if batch.panel else "no")
    if a.tv_trades:
        from nifty.parity.cli import _bc_lines
        from nifty.parity.compare import tier_bc
        from nifty.parity.tv_io import load_tv_trades

        tv = load_tv_trades(a.tv_trades)
        lo, hi = bars[0].bar_start_utc, bars[-1].bar_start_utc
        tv = [x for x in tv if lo <= x.entry_time <= hi]
        step = timedelta(minutes=int(tf.rstrip("m")))
        print("\n".join(_bc_lines(f"vs TradingView ({len(tv)} trades in range)", tier_bc(batch.trades, tv, step, 0.005, 0.005))))
    print("RESULT:", "stable" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
