"""`parity --engine ID [--golden DIR] [--oracle PATH]`: prints <=30 lines (spec/04)."""

from datetime import timedelta
from pathlib import Path

from nifty.contracts import Instrument
from nifty.parity.compare import TierBC, tier_a, tier_bc
from nifty.parity.tv_io import (
    load_oracle_trades,
    load_tv_ohlc_plots,
    load_tv_trades,
    parse_time,
    tv_bars,
)

REPO = Path(__file__).resolve().parents[4]
ORACLE_DATA = REPO / "reference" / "oracle" / "data" / "nifty_1m.csv"
ORACLE_TRADES = REPO / "reference" / "oracle" / "logs" / "scalper_trades.csv"
SYMBOL, TICK = (
    "NIFTY 50",
    0.05,
)  # oracle dataset facts (docs/SOURCES.md); tick is given, not inferred

SHORT = {"pine.nvs_scalper": "nvs"}

# TradingView plot titles -> engine plot names (Pine L322-334)
SERIES: dict[str, dict[str, str]] = {
    "pine.nvs_scalper": {
        "VWAP (TWAP if no volume)": "vwap", "EMA fast": "ema_fast", "EMA slow": "ema_slow",
        "Buy zone near": "buy_near", "Buy zone far": "buy_far", "Sell zone near": "sell_near",
        "Sell zone far": "sell_far", "Stop": "stop", "Target": "target",
    }
}  # fmt: skip


def _bc_lines(label: str, r: TierBC, limit: int = 5) -> list[str]:
    out = [
        f"{label}: ours {r.n_ours} ref {r.n_ref} | entries {r.entries_ok}/{r.n_ref} "
        f"| exits {r.exits_ok}/{r.n_ref}"
    ]
    out += [f"  {d}" for d in r.diffs[:limit]]
    if len(r.diffs) > limit:
        out.append(f"  ... {len(r.diffs) - limit} more")
    return out


def run_parity(
    engine_id: str, golden: Path | None = None, oracle: Path | None = None
) -> tuple[list[str], int]:
    from nifty.engines.base import get_engine, load_builtin_engines
    from nifty.engines.runner import run_batch
    from nifty.marketdata.importer import parse_csv
    from nifty.marketdata.validation import validate_bars
    from nifty.timeutil import Calendar

    load_builtin_engines()
    spec = get_engine(engine_id)
    cal = Calendar.load()
    tf = spec.cls.default_timeframe
    tfd = timedelta(minutes=int(tf.rstrip("m")))
    iid = f"csv:{SYMBOL}"
    inst = Instrument(instrument_id=iid, provider="csv", tradingsymbol=SYMBOL, tick_size=TICK)
    lines: list[str] = []
    gdir = golden or REPO / "fixtures" / "tv_golden" / engine_id
    if golden is None and not gdir.exists():  # RUNBOOK uses the short name
        gdir = REPO / "fixtures" / "tv_golden" / SHORT.get(engine_id, engine_id)
    ran = False

    if (gdir / "ohlc_plots.csv").exists():
        rows, cols = load_tv_ohlc_plots(gdir / "ohlc_plots.csv")
        res = run_batch(engine_id, {}, tv_bars(rows, iid, tf), tf, instrument=inst, calendar=cal)
        smap = SERIES.get(engine_id, {})
        g = {
            smap[c]: {
                parse_time({k.lower(): v for k, v in r.items()}["time"]): float(r[c] or "nan")
                for r in rows
            }
            for c in cols if c in smap
        }  # fmt: skip
        a = tier_a(res.plots, g, spec.cls.warmup_bars)
        worst = ", ".join(f"{k} {m:.2e}" for k, (m, _) in a.series.items())
        lines.append(f"TV golden {gdir.name}: {len(rows)} bars · Tier A {'OK' if a.ok else 'FAIL'}")
        lines.append(f"  max abs err: {worst}")
        lines += [f"  {d}" for d in a.diffs]
        if (gdir / "trades.csv").exists():
            lines += _bc_lines(
                "Tier B/C vs TV",
                tier_bc(res.trades, load_tv_trades(gdir / "trades.csv"), tfd, 0.005, 0.005),
            )
        ran = True
    else:
        lines.append("golden missing")

    if engine_id == "pine.nvs_scalper" or oracle is not None:
        data, tr = ORACLE_DATA, oracle or ORACLE_TRADES
        if data.exists() and tr.exists():
            bars, _ = validate_bars(parse_csv(data, instrument_id=iid), cal)
            res = run_batch(
                engine_id, {"anchor_mode": "signal_close"}, bars, tf, instrument=inst, calendar=cal
            )
            lines += _bc_lines(
                "Oracle (twin, signal_close)", tier_bc(res.trades, load_oracle_trades(tr), tfd)
            )
            ran = True
    return lines[:30], 0 if ran or lines == ["golden missing"] else 2
