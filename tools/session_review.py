"""Live-session review (read-only on market data; never places orders).

  python tools/session_review.py monitor [--every 15]   # run in a 2nd terminal during the session
  python tools/session_review.py report  [--date YYYY-MM-DD] [--symbol "NIFTY 50"]

`monitor` appends one JSON line per sample to logs/session/<date>/monitor.jsonl: collector state (ticks, tick age,
reconnects, bad packets), API /healthz latency, DB write counts, CPU % and RSS of the nifty processes (from /proc,
no extra packages). `report` writes logs/session/<date>/report.md plus events.csv, trades.csv, latency.csv:
bars completeness, tick gaps and exchange->received latency, resource summary, live events per engine, trades the
engines suggested, and a live-vs-batch consistency check (D14: the live events must equal a batch rerun on the stored bars).
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from sqlalchemy import text  # noqa: E402

from nifty.timeutil import IST, Calendar  # noqa: E402


def out_dir(d: date) -> Path:
    p = ROOT / "logs" / "session" / d.isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return p


def today_ist() -> date:
    return datetime.now(IST).date()


# ---- monitor ------------------------------------------------------------------------------------
def procs() -> dict[int, tuple[str, float, int]]:
    """pid -> (label, cpu_seconds, rss_mb) for processes whose command line mentions nifty."""
    tick = os.sysconf("SC_CLK_TCK")
    found: dict[int, tuple[str, float, int]] = {}
    for pid in (int(p) for p in os.listdir("/proc") if p.isdigit()):
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
            if "nifty" not in cmd and "vite" not in cmd and "uvicorn" not in cmd:
                continue
            if "session_review" in cmd:
                continue
            st = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            cpu = (int(st[11]) + int(st[12])) / tick
            rss = 0
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS"):
                    rss = int(line.split()[1]) // 1024
            label = ("collector" if "collector" in cmd else "worker" if "worker" in cmd
                     else "api" if "uvicorn" in cmd else "web" if "vite" in cmd else "other")  # fmt: skip
            found[pid] = (label, cpu, rss)
        except (OSError, IndexError, ValueError):
            continue
    return found


def monitor(every: float) -> int:
    from nifty.db.live import read_status
    from nifty.db.session import get_engine

    eng = get_engine()
    path = out_dir(today_ist()) / "monitor.jsonl"
    prev: dict[int, tuple[str, float, int]] = {}
    t_prev = time.monotonic()
    print(f"sampling every {every}s -> {path} (Ctrl-C to stop)")
    try:
        while True:
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=3) as r:
                    health_ms: float | None = round((time.monotonic() - t0) * 1000, 1)
                    ok = r.status == 200
            except OSError:
                health_ms, ok = None, False
            with eng.connect() as c:
                st = read_status(c)
                nticks = c.execute(text("SELECT count(*) FROM ticks WHERE ts_received > now() - interval '1 minute'")).scalar()
                nbars = c.execute(text("SELECT count(*) FROM bars WHERE timeframe='1m' AND bar_start_utc >= :d"), {"d": datetime.combine(today_ist(), datetime.min.time(), IST).astimezone(UTC)}).scalar()
            now = time.monotonic()
            cur = procs()
            res = {}
            for pid, (label, cpu, rss) in cur.items():
                dcpu = cpu - prev[pid][1] if pid in prev else 0.0
                r_ = res.setdefault(label, {"cpu_pct": 0.0, "rss_mb": 0})
                r_["cpu_pct"] = round(r_["cpu_pct"] + 100 * dcpu / max(now - t_prev, 1e-9), 1)
                r_["rss_mb"] += rss
            prev, t_prev = cur, now
            data, age = (st if st else ({}, None))
            row = {"t": datetime.now(UTC).isoformat(timespec="seconds"), "api_ok": ok, "healthz_ms": health_ms,
                   "collector": {k: data.get(k) for k in ("connected", "stale", "auth_expired", "ticks", "reconnects", "bad_packets", "late_ticks", "last_tick_age_s", "redis")},
                   "status_age_s": None if age is None else round(age, 1), "ticks_last_min": nticks,
                   "bars_today": nbars, "procs": res}  # fmt: skip
            with path.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
            time.sleep(max(0.0, every - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        return 0


# ---- report -------------------------------------------------------------------------------------
def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))] if s else float("nan")


def report(day: date, symbol: str) -> int:
    from nifty.db.bars import read_bars
    from nifty.db.instruments import find_instrument
    from nifty.db.session import get_engine
    from nifty.engines.base import load_builtin_engines
    from nifty.engines.runner import run_batch

    load_builtin_engines()
    cal = Calendar.load()
    lo, hi = cal.session_bounds(day)
    d = out_dir(day)
    md: list[str] = [f"# Session review {day} ({symbol})", ""]
    eng = get_engine()
    with eng.connect() as c:
        ins = find_instrument(c, symbol)
        if ins is None:
            print("unknown symbol; Settings -> Refresh instruments")
            return 2
        iid = ins.instrument_id
        # --- bars completeness
        starts = [r[0] for r in c.execute(text("SELECT bar_start_utc FROM bars WHERE instrument_id=:i AND timeframe='1m' AND bar_start_utc>=:a AND bar_start_utc<:b ORDER BY 1"), {"i": iid, "a": lo, "b": hi})]
        expected = int((hi - lo).total_seconds() // 60)
        have = set(starts)
        missing = [lo + timedelta(minutes=i) for i in range(expected) if lo + timedelta(minutes=i) not in have]
        md += ["## Data", f"- 1m bars stored: {len(starts)} of {expected} expected; missing {len(missing)}"
               + (f" (first {missing[0].astimezone(IST):%H:%M}, last {missing[-1].astimezone(IST):%H:%M} IST)" if missing else ""), ""]
        # --- ticks: rate, gaps, latency
        rows = c.execute(text("SELECT ts_exchange, ts_received FROM ticks WHERE instrument_id=:i AND ts_exchange>=:a AND ts_exchange<:b ORDER BY 1"), {"i": iid, "a": lo, "b": hi}).all()
        lat = [(r[1] - r[0]).total_seconds() * 1000 for r in rows]
        gaps = sorted(((b[0] - a[0]).total_seconds(), a[0]) for a, b in zip(rows, rows[1:], strict=False))[-5:]
        md += ["## Ticks", f"- {len(rows)} ticks for the index" + (f"; latency exchange->received ms: p50 {pct(lat, .5):.0f}, p95 {pct(lat, .95):.0f}, max {max(lat):.0f}" if lat else "")]
        md += [f"- longest gaps (s): " + ", ".join(f"{g:.0f}@{t.astimezone(IST):%H:%M:%S}" for g, t in reversed(gaps))] if gaps else []
        with (d / "latency.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts_exchange", "latency_ms"])
            w.writerows((r[0].isoformat(), round(l_, 1)) for r, l_ in zip(rows, lat, strict=True))
        md += [""]
        # --- live events per engine
        runs = c.execute(text("SELECT run_id, engine_id, config_hash, timeframe FROM engine_runs WHERE instrument_id=:i AND source_id LIKE 'live:%'"), {"i": iid}).all()
        ev_rows: list[dict[str, Any]] = []
        md += ["## Live engine output"]
        trades_started = False
        for rid, eid, chash, tf in runs:
            evs = c.execute(text("SELECT event_type, bar_start_utc, available_at_utc, envelope FROM events WHERE run_id=:r AND confirmed_or_provisional='confirmed' AND bar_start_utc>=:a AND bar_start_utc<:b ORDER BY bar_start_utc, ord"), {"r": rid, "a": lo, "b": hi}).all()
            by: dict[str, int] = {}
            for t, b, av, env in evs:
                by[t] = by.get(t, 0) + 1
                ev_rows.append({"engine": eid, "type": t, "bar_start_ist": b.astimezone(IST).strftime("%H:%M"), "available_ist": av.astimezone(IST).strftime("%H:%M:%S"),
                                "lag_s_after_bar_end": round((av - (b + timedelta(minutes=1))).total_seconds(), 1), "payload": json.dumps(env.get("payload", {}), default=str)})  # fmt: skip
            md.append(f"- {eid} ({tf}): " + (", ".join(f"{k} {v}" for k, v in sorted(by.items())) or "no events"))
            # --- D14: batch rerun on the stored bars must give the same confirmed events
            params = c.execute(text("SELECT params FROM engine_configs WHERE config_hash=:h AND engine_id=:e"), {"h": chash, "e": eid}).scalar() or {}
            warm = lo - timedelta(days=10)
            bars = read_bars(c, iid, "1m", warm, hi)
            res = run_batch(eid, params, bars, tf, instrument=ins, calendar=cal)
            batch = {(e.event_type, e.bar_start_utc) for e in res.events if lo <= e.bar_start_utc < hi}
            live = {(t, b) for t, b, _, _ in evs}
            md.append(f"  - live vs batch rerun: live-only {len(live - batch)}, batch-only {len(batch - live)} "
                      + ("(MATCH)" if live == batch else "(MISMATCH: investigate, list in events.csv)"))  # fmt: skip
            for t, b in sorted(live ^ batch):
                ev_rows.append({"engine": eid, "type": f"MISMATCH:{t}", "bar_start_ist": b.astimezone(IST).strftime("%H:%M"), "available_ist": "", "lag_s_after_bar_end": "", "payload": "live-only" if (t, b) in live else "batch-only"})  # fmt: skip
            day_trades = [t for t in res.trades if lo <= t.entry_time < hi]
            md.append(f"  - trades suggested (batch on stored bars): {len(day_trades)}; net pts {sum(t.net_pts for t in day_trades):.2f}")
            mode = "a" if trades_started else "w"
            trades_started = True
            with (d / "trades.csv").open(mode, newline="") as f:
                w = csv.writer(f)
                if mode == "w":
                    w.writerow(["engine", "tf", "side", "signal_ist", "entry_ist", "entry_px", "exit_ist", "exit_px", "reason", "net_pts", "flags"])
                for t in day_trades:
                    w.writerow([eid, tf, t.side, t.signal_bar_start.astimezone(IST).strftime("%H:%M") if t.signal_bar_start else "", t.entry_time.astimezone(IST).strftime("%H:%M"), t.entry_px, t.exit_time.astimezone(IST).strftime("%H:%M"), t.exit_px, t.exit_reason, round(t.net_pts, 2), "|".join(t.flags)])  # fmt: skip
        if not runs:
            md.append("- no live runs recorded for this instrument")
        if ev_rows:
            with (d / "events.csv").open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(ev_rows[0]))
                w.writeheader()
                w.writerows(ev_rows)
            lags = [r["lag_s_after_bar_end"] for r in ev_rows if isinstance(r["lag_s_after_bar_end"], float)]
            if lags:
                md.append(f"- event availability lag after bar end (s): p50 {pct(lags, .5):.1f}, p95 {pct(lags, .95):.1f}, max {max(lags):.1f}")
        md.append("")
        # --- option recording
        n_opt = c.execute(text("SELECT count(DISTINCT instrument_id) FROM ticks WHERE instrument_id LIKE '%:NFO:%' AND ts_exchange>=:a AND ts_exchange<:b"), {"a": lo, "b": hi}).scalar()
        md += ["## Options", f"- distinct option contracts with ticks: {n_opt}", ""]
    # --- resources from the monitor file
    mon = d / "monitor.jsonl"
    md.append("## Resources and health")
    if mon.exists():
        s = [json.loads(x) for x in mon.read_text().splitlines() if x.strip()]
        h = [x["healthz_ms"] for x in s if x["healthz_ms"] is not None]
        down = sum(1 for x in s if not x["api_ok"])
        rec = [x["collector"].get("reconnects") or 0 for x in s]
        stale = sum(1 for x in s if x["collector"].get("stale"))
        md.append(f"- {len(s)} samples; API down in {down}; /healthz ms p50 {statistics.median(h):.0f}, max {max(h):.0f}" if h else f"- {len(s)} samples; API never answered")
        md.append(f"- collector: reconnects {max(rec) if rec else 0}, stale samples {stale}, bad packets {max((x['collector'].get('bad_packets') or 0) for x in s)}, late ticks {max((x['collector'].get('late_ticks') or 0) for x in s)}")
        for lab in sorted({k for x in s for k in x["procs"]}):
            cpu = [x["procs"][lab]["cpu_pct"] for x in s if lab in x["procs"]]
            rss = [x["procs"][lab]["rss_mb"] for x in s if lab in x["procs"]]
            md.append(f"- {lab}: CPU % p50 {statistics.median(cpu):.1f}, max {max(cpu):.1f}; RSS MB start {rss[0]}, end {rss[-1]}, max {max(rss)}")
    else:
        md.append("- no monitor.jsonl (run `make session-monitor` during the session)")
    (d / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"\nwritten: {d}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("monitor")
    m.add_argument("--every", type=float, default=15.0)
    r = sub.add_parser("report")
    r.add_argument("--date", type=date.fromisoformat, default=today_ist())
    r.add_argument("--symbol", default="kite:NSE:NIFTY 50")
    a = ap.parse_args()
    return monitor(a.every) if a.cmd == "monitor" else report(a.date, a.symbol)


if __name__ == "__main__":
    raise SystemExit(main())
