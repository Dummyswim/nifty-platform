"""`make bench`: replay ~100k SYNTHETIC 1m bars through the NVS engine. Prints bars/s and peak RSS.

The oracle sessions are tiled onto consecutive weekdays; the data is generated in memory, labelled
synthetic and never stored. Report only; no tuning (C04)."""

import resource
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend" / "src"))

from nifty.contracts import Bar, Instrument  # noqa: E402
from nifty.engines.base import load_builtin_engines  # noqa: E402
from nifty.engines.runner import run_batch, run_incremental  # noqa: E402
from nifty.marketdata.importer import parse_csv  # noqa: E402
from nifty.marketdata.validation import validate_bars  # noqa: E402
from nifty.timeutil import Calendar  # noqa: E402

TARGET = 100_000


def synthetic_bars(cal: Calendar) -> list[Bar]:
    src, _ = validate_bars(
        parse_csv(REPO / "reference/oracle/data/nifty_1m.csv", instrument_id="synthetic:bench"), cal
    )
    sessions: dict[date, list[Bar]] = {}
    for b in src:
        sessions.setdefault(cal.session_date(b.bar_start_utc), []).append(b)
    days = list(sessions.values())
    out: list[Bar] = []
    d, i = date(2024, 1, 1), 0
    while len(out) < TARGET:
        if d.weekday() < 5:
            day = days[i % len(days)]
            i += 1
            o_src = cal.session_bounds(cal.session_date(day[0].bar_start_utc))[0]
            o_dst = cal.session_bounds(d)[0]
            for b in day:
                s = o_dst + (b.bar_start_utc - o_src)
                out.append(
                    b.model_copy(update={"bar_start_utc": s, "bar_end_utc": s + timedelta(minutes=1)})
                )
        d += timedelta(days=1)
    return out


def main() -> int:
    load_builtin_engines()
    cal = Calendar.load()
    ins = Instrument(
        instrument_id="synthetic:bench", provider="csv", tradingsymbol="BENCH", tick_size=0.05
    )
    bars = synthetic_bars(cal)
    print(f"SYNTHETIC data (oracle sessions tiled onto weekdays): {len(bars)} 1m bars")
    for name, fn in (("batch", run_batch), ("incremental", run_incremental)):
        t0 = time.perf_counter()
        r = fn("pine.nvs_scalper", {}, bars, "5m", instrument=ins, calendar=cal)
        dt = time.perf_counter() - t0
        print(
            f"{name:<12} {len(bars) / dt:>10,.0f} 1m bars/s · {len(r.bars) / dt:>8,.0f} chart bars/s"
            f" · {dt:.1f}s · trades {len(r.trades)}"
        )
    print(f"peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
