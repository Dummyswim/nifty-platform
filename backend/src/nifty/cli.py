import argparse
import getpass
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import Connection

from nifty.contracts import TF_MINUTES, Instrument
from nifty.security import hash_password
from nifty.timeutil import Calendar, to_ist

if TYPE_CHECKING:
    from nifty.marketdata.kite.client import KiteClient


def _hhmm(dt: datetime) -> str:
    return to_ist(dt).strftime("%H:%M")


def session_range(
    cal: Calendar, from_date: str | None, to_date: str | None
) -> tuple[datetime | None, datetime | None]:
    """Inclusive session dates -> [first open, last close) in UTC; None where omitted."""
    lo = cal.session_bounds(date.fromisoformat(from_date))[0] if from_date else None
    hi = cal.session_bounds(date.fromisoformat(to_date))[1] if to_date else None
    return lo, hi


def _import_csv(a: argparse.Namespace) -> int:
    from nifty.db.bars import upsert_bars
    from nifty.db.instruments import upsert_instrument
    from nifty.db.session import get_engine
    from nifty.marketdata.importer import ImportRejected, parse_file
    from nifty.marketdata.validation import validate_bars

    iid = f"csv:{a.symbol}"
    try:
        raw = parse_file(Path(a.path), instrument_id=iid, tz=a.tz)
    except ImportRejected as e:
        print(f"REJECTED: {e}")
        return 2
    bars, r = validate_bars(raw, Calendar.load())
    print(f"rows_in {r.rows_in} · accepted {r.rows_ok} · excluded {len(r.excluded)}", end="")
    print(f" · duplicates {r.duplicates} · out_of_order {r.out_of_order}")
    for ex in r.excluded[:3]:
        print(f"  excluded {ex.reason} {to_ist(ex.ts).isoformat()}")
    if len(r.excluded) > 3:
        print(f"  ... {len(r.excluded) - 3} more excluded")
    if r.sessions:
        f, last = r.sessions[0], r.sessions[-1]
        print(
            f"sessions {len(r.sessions)} · first {f.date} starts {_hhmm(f.first)} n={f.n}", end=""
        )
        print(f" · last {last.date} ends {_hhmm(last.last)} n={last.n}")
        odd = [s for s in r.sessions[1:-1] if s.n != 375]
        if odd:
            print("  other short sessions: " + ", ".join(f"{s.date} n={s.n}" for s in odd[:6]))
    for g in r.gaps[:5]:
        print(f"  gap {g.day} {_hhmm(g.from_ts)}-{_hhmm(g.to_ts)} missing={g.missing}")
    if len(r.gaps) > 5:
        print(f"  ... {len(r.gaps) - 5} more gaps")
    print(
        f"volume_kind {r.volume_kind}" + (" · calendar_unverified" if r.calendar_unverified else "")
    )
    if a.dry_run:
        print("dry-run: nothing stored")
        return 0
    ins = Instrument(
        instrument_id=iid, provider="csv", tradingsymbol=a.symbol, tick_size=a.tick_size
    )
    with get_engine().begin() as conn:
        upsert_instrument(conn, ins)
        u = upsert_bars(conn, bars)
    print(f"stored: inserted {u.inserted} · revised {u.revised} · unchanged {u.noop}")
    return 0


def _find(conn: Connection, symbol: str) -> Instrument | None:
    from nifty.db.instruments import find_by_symbol

    ins = find_by_symbol(conn, symbol)
    if ins is None:
        print(f"unknown symbol {symbol!r}; import data first")
    return ins


def _bars(a: argparse.Namespace) -> int:
    from nifty.db.bars import read_bars
    from nifty.db.session import get_engine
    from nifty.marketdata.resample import resample

    with get_engine().connect() as conn:
        ins = _find(conn, a.symbol)
        if ins is None:
            return 2
        per = 375 if a.tf == "1d" else TF_MINUTES[a.tf]
        # one extra bucket so the oldest shown bucket is never cut by the read window
        raw = read_bars(conn, ins.instrument_id, "1m", last_n=(a.n + 1) * per + 375)
    out = raw if a.tf == "1m" else resample(raw, a.tf, Calendar.load())
    shown = out[-a.n :]
    print(f"{a.symbol} {a.tf} · {len(raw)} 1m bars read · last {len(shown)}")
    for b in shown:
        flags = ",".join(b.quality_flags) + ("" if b.finalized else ",open")
        print(
            f"{to_ist(b.bar_start_utc):%Y-%m-%d %H:%M} o={b.open:.2f} h={b.high:.2f} l={b.low:.2f} "
            f"c={b.close:.2f} v={b.volume:g} {flags.strip(',')}"
        )
    return 0


def _snapshot(a: argparse.Namespace) -> int:
    from nifty.db.bars import create_snapshot
    from nifty.db.session import get_engine

    start, end = session_range(Calendar.load(), a.from_date, a.to_date)
    assert start is not None and end is not None
    with get_engine().begin() as conn:
        ins = _find(conn, a.symbol)
        if ins is None:
            return 2
        try:
            s = create_snapshot(conn, ins.instrument_id, a.tf, start, end)
        except ValueError as e:
            print(f"no snapshot: {e}")
            return 2
    print(f"snapshot_id {s.snapshot_id}\nsha256 {s.sha256}")
    print(f"rows {s.n_rows} · {a.tf} · {a.from_date}..{a.to_date} (inclusive session dates)")
    return 0


def run_engine(
    conn: Connection,
    *,
    engine_id: str,
    symbol: str,
    timeframe: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    params: str | None = None,
    persist: bool = True,
    allow_unready: bool = False,
) -> list[str]:
    """Run an engine over stored 1m bars; returns <=15 summary lines. Takes a connection so tests
    can run it on nifty_test. Only this developer path may run `ready=False` engines."""
    from nifty.db.bars import create_snapshot, read_bars
    from nifty.engines.base import EngineNotFound, EngineNotReady, get_engine
    from nifty.engines.runner import run_batch

    try:
        spec = get_engine(engine_id, allow_unready)
    except EngineNotFound:
        return [f"unknown engine {engine_id!r}"]
    except EngineNotReady as e:
        return [f"refused: {e} (use --allow-unready for development)"]
    ins = _find(conn, symbol)
    if ins is None:
        return [f"unknown symbol {symbol!r}; import data first"]
    cal = Calendar.load()
    lo, hi = session_range(cal, from_date, to_date)
    bars = read_bars(conn, ins.instrument_id, "1m", lo, hi)
    if not bars:
        return ["no 1m bars in range"]
    # same bounds as `nifty.cli snapshot`, so both paths yield the same snapshot_id
    start, end = session_range(
        cal,
        from_date or cal.session_date(bars[0].bar_start_utc).isoformat(),
        to_date or cal.session_date(bars[-1].bar_start_utc).isoformat(),
    )
    assert start is not None and end is not None
    raw = params or ""
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text()
    res_params = json.loads(raw) if raw else {}
    tf = timeframe or spec.cls.default_timeframe
    if persist:
        snap = create_snapshot(conn, ins.instrument_id, "1m", start, end)
        source_id = snap.snapshot_id
    else:
        source_id = "adhoc"
    r = run_batch(
        engine_id, res_params, bars, tf, instrument=ins, calendar=cal, source_id=source_id,
        allow_unready=allow_unready,
    )  # fmt: skip
    cols = sorted({k for _, p in r.plots for k in p})
    lines = [
        f"engine {r.engine_id} v{r.engine_version} · {symbol} {tf} · config {r.config_hash[:12]}",
        f"1m bars {len(bars)} -> chart bars {len(r.bars)} · source {source_id}",
        f"plots {len(r.plots)} rows: {', '.join(cols[:8])}",
        f"events {len(r.events)} · overlays {len(r.overlays)} · trades {len(r.trades)}",
    ]
    if persist:
        from nifty.db.runs import persist_run

        run_id, created = persist_run(conn, r)
        lines.append(f"run_id {run_id} ({'created' if created else 'existing, nothing written'})")
    else:
        lines.append("not persisted (--no-persist)")
    return lines


def _run_engine_cli(a: argparse.Namespace) -> int:
    from nifty.db.session import get_engine
    from nifty.engines.base import load_builtin_engines

    load_builtin_engines()
    with get_engine().begin() as conn:
        lines = run_engine(
            conn, engine_id=a.engine, symbol=a.symbol, timeframe=a.timeframe,
            from_date=a.from_date, to_date=a.to_date, params=a.params,
            persist=not a.no_persist, allow_unready=a.allow_unready,
        )  # fmt: skip
    print("\n".join(lines[:15]))
    return 0 if lines and not lines[0].startswith(("unknown", "refused", "no ")) else 2


def format_metrics(m: dict[str, object]) -> list[str]:
    def f(x: object, nd: int = 2) -> str:
        return "n/a" if x is None else f"{x:.{nd}f}" if isinstance(x, float) else str(x)

    return [
        f"trades {m['n_trades']} (W {m['wins']} / L {m['losses']}) · "
        f"win_rate {f(m['win_rate'], 3)}",
        f"total_pnl_pts {f(m['total_pnl_pts'])} · expectancy_pts {f(m['expectancy_pts'])}",
        f"profit_factor {f(m['profit_factor'])} · max_drawdown_pts {f(m['max_drawdown_pts'])}",
        f"max consecutive wins {m['max_consecutive_wins']} / losses {m['max_consecutive_losses']}",
        f"sharpe {f(m['sharpe'])} over {m['n_sessions']} sessions"
        + (" (LOW N: < 30 sessions)" if m["low_n"] else ""),
        f"flags: {', '.join(m['flags']) or 'none'}",  # type: ignore[arg-type]
    ]


def _backtest_cli(a: argparse.Namespace) -> int:
    from nifty.db.backtests import BacktestError, get_backtest, run_backtest
    from nifty.db.session import get_engine

    payload = {
        k: v
        for k, v in {
            "engine_id": a.engine, "symbol": a.symbol, "timeframe": a.timeframe,
            "from_date": a.from_date, "to_date": a.to_date, "mode": a.mode, "qty": a.qty,
            "cost_pts": a.cost_pts, "params": json.loads(a.params) if a.params else None,
        }.items()
        if v is not None
    }  # fmt: skip
    try:
        with get_engine().begin() as conn:
            bt_id = run_backtest(conn, payload)
            row = get_backtest(conn, bt_id)
    except BacktestError as e:
        print(f"refused: {e}")
        return 2
    assert row is not None
    print(f"backtest {bt_id} · {row['engine_id']} {row['timeframe']} {row['mode']}")
    print(f"snapshot {row['snapshot_id']}")
    print("\n".join(format_metrics(row["summary"])))
    return 0


def _kite_client(conn: Connection) -> "KiteClient":
    from nifty.config import get_settings
    from nifty.db.kite import client_for

    return client_for(conn, get_settings())


def _kite_instruments(a: argparse.Namespace) -> int:
    from nifty.db.kite import save_master
    from nifty.db.session import get_engine
    from nifty.marketdata.base import ProviderError
    from nifty.marketdata.kite.master import expiries, front_month_future, nifty_index, strike_step
    from nifty.timeutil import utcnow

    try:
        with get_engine().begin() as conn:
            version, ins = save_master(conn, _kite_client(conn).instruments())
    except ProviderError as e:
        print(f"FAIL {e}")
        return 2
    fut = front_month_future(ins, utcnow().date())
    exp = expiries(ins, "CE")
    idx = nifty_index(ins)
    print(f"master {version}: {len(ins)} NIFTY instruments stored")
    fut_name = fut.tradingsymbol if fut else "none"
    print(f"index {idx.tradingsymbol if idx else 'MISSING'} · front-month future {fut_name}")
    print(f"option expiries {len(exp)} · strike step {strike_step(ins, exp[0]) if exp else 'n/a'}")
    return 0


def _kite_backfill(a: argparse.Namespace) -> int:
    from nifty.db.session import get_engine
    from nifty.marketdata.base import ProviderError
    from nifty.worker.handlers import kite_backfill

    try:
        with get_engine().begin() as conn:
            print(
                kite_backfill(
                    conn, {"symbol": a.symbol, "from_date": a.from_date, "to_date": a.to_date}
                )
            )
    except (ProviderError, ValueError) as e:
        print(f"FAIL {e}")
        return 2
    return 0


def _set_tick_size(a: argparse.Namespace) -> int:
    """Indexes have no tick size in the Kite master; the user supplies it (survives refreshes)."""
    from sqlalchemy import text

    from nifty.db.session import get_engine

    if a.tick <= 0:
        print("FAIL tick must be > 0")
        return 2
    with get_engine().begin() as conn:
        n = conn.execute(
            text("UPDATE instruments SET tick_size = :t WHERE instrument_id = :i"),
            {"t": a.tick, "i": a.instrument},
        ).rowcount
    print(
        f"tick_size={a.tick} set on {a.instrument}"
        if n
        else f"FAIL no such instrument {a.instrument}"
    )
    return 0 if n else 2


def _kite_smoke(a: argparse.Namespace) -> int:
    """User-run live check. Prints PASS/FAIL/INFO lines; never a secret."""
    from datetime import timedelta

    from nifty.config import get_settings
    from nifty.db.kite import load_token
    from nifty.db.session import get_engine
    from nifty.marketdata.base import ProviderError
    from nifty.marketdata.kite.client import KiteClient
    from nifty.marketdata.kite.master import nifty_index, parse_master
    from nifty.timeutil import IST, utcnow

    s = get_settings()
    fails = 0

    def line(ok: bool | None, msg: str) -> None:
        nonlocal fails
        fails += ok is False
        print(("PASS" if ok else "FAIL" if ok is False else "INFO"), msg)

    line(
        bool(s.kite_api_key and s.kite_api_secret),
        "credentials present in .env (key and secret set)",
    )
    with get_engine().connect() as conn:
        token = load_token(conn, s.app_secret_key)
    line(token is not None, "access token stored and unexpired (Settings -> Connect Kite)")
    if not token or not s.kite_api_key:
        return 2
    client = KiteClient(s.kite_api_key, s.kite_api_secret, token)
    try:
        prof = client.profile()
        line(True, f"profile ok (user_id {prof.get('user_id')})")
        ins = parse_master(client.instruments(), "smoke")
        idx = nifty_index(ins)
        line(
            idx is not None and len(ins) > 100,
            f"instrument master: {len(ins)} NIFTY rows, index {'found' if idx else 'MISSING'}",
        )
        if idx is None or idx.provider_token is None:
            return 2
        day = utcnow().astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
        for back in range(1, 8):  # latest weekday with data
            d0 = day - timedelta(days=back)
            if d0.weekday() >= 5:
                continue
            c = client.historical(
                idx.provider_token,
                "minute",
                d0.replace(hour=9, minute=15),
                d0.replace(hour=15, minute=30),
            )
            if c:
                line(
                    len(c) > 300,
                    f"1m candles for {d0:%Y-%m-%d}: {len(c)} (expect ~375); first {c[0][0]}",
                )
                break
        else:
            line(False, "no 1m candles for the last 7 days")
        if a.probe_limits:
            for n in (60, 61):
                try:
                    client.historical(
                        idx.provider_token,
                        "minute",
                        day - timedelta(days=n),
                        day - timedelta(days=1),
                    )
                    line(None, f"minute range of {n} days accepted")
                except ProviderError as e:
                    line(None, f"minute range of {n} days rejected: {e}")
    except ProviderError as e:
        line(False, f"{e}")
    print("RESULT", "FAIL" if fails else "PASS")
    return 1 if fails else 0


def research_counts(conn: Connection, symbol: str) -> list[str]:
    """Outcome counts per baseline x experiment (target 10/20) on stored 1m bars; counts only."""
    from collections import Counter

    from nifty.db.bars import read_bars
    from nifty.engines.base import load_builtin_engines
    from nifty.engines.runner import run_batch

    load_builtin_engines()
    ins = _find(conn, symbol)
    if ins is None:
        return [f"unknown symbol {symbol!r}; import data first"]
    cal = Calendar.load()
    bars = read_bars(conn, ins.instrument_id, "1m")
    lines = [
        f"research.distance_entry_v1 on {symbol} 1m ({len(bars)} bars; stop 12, hold 10, cost 0): "
        "counts only, no performance claim",
        f"{'baseline':<30}{'tgt':>4}{'n':>5}{'TARGET':>8}{'STOP':>6}{'TIME':>6}{'ambig':>6}{'cut':>5}{'gap':>5}",
    ]
    for base in (
        "anchor_cross_ema_order",
        "ema_gap_reexpansion",
        "ema_aligned_gap_reexpansion",
        "armed_resumption",
    ):
        for tgt in (10, 20):
            r = run_batch(
                "research.distance_entry_v1", {"baseline": base, "target_pts": tgt}, bars, "1m",
                instrument=ins, calendar=cal, source_id="counts",
            )  # fmt: skip
            c = Counter(t.exit_reason for t in r.trades)
            fl = Counter(f for t in r.trades for f in t.flags)
            lines.append(
                f"{base:<30}{tgt:>4}{len(r.trades):>5}{c['TARGET_FIRST']:>8}{c['STOP_FIRST']:>6}"
                f"{c['TIME_EXIT']:>6}{fl['ambiguous_bar']:>6}{fl['session_cut']:>5}{fl['data_gap']:>5}"
            )
    return lines


def _research_counts_cli(a: argparse.Namespace) -> int:
    from nifty.db.session import get_engine

    with get_engine().connect() as conn:
        lines = research_counts(conn, a.symbol)
    print("\n".join(lines[:20]))
    return 0


def _demo_replay(a: argparse.Namespace) -> int:
    import logging

    from nifty.collector.demo import run_demo

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    return run_demo(a.speed, a.max_sessions, a.from_date, not a.exit_at_end)


def _parity(a: argparse.Namespace) -> int:
    from nifty.parity.cli import run_parity

    lines, rc = run_parity(
        a.engine, Path(a.golden) if a.golden else None, Path(a.oracle) if a.oracle else None
    )
    print("\n".join(lines))
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nifty")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hash-password", help="prompt and print APP_PASSWORD_HASH=...")
    sub.add_parser("openapi", help="print the OpenAPI JSON")
    p = sub.add_parser("import-csv", help="validate and store a 1m CSV/JSON file")
    p.add_argument("path")
    p.add_argument("--symbol", required=True)
    p.add_argument("--tick-size", type=float, required=True, help="never inferred")
    p.add_argument("--tz", help="IANA tz for naive timestamps, e.g. Asia/Kolkata")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("bars", help="summary and last N bars")
    p.add_argument("--symbol", required=True)
    p.add_argument("--tf", default="1m")
    p.add_argument("--n", type=int, default=5)
    p = sub.add_parser("snapshot", help="create/reuse a dataset snapshot")
    p.add_argument("--symbol", required=True)
    p.add_argument("--from", dest="from_date", required=True, help="first session date (inclusive)")
    p.add_argument("--to", dest="to_date", required=True, help="last session date (inclusive)")
    p.add_argument("--tf", default="1m")
    p = sub.add_parser("run-engine", help="run an engine over stored 1m bars (developer tool)")
    p.add_argument("--engine", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe")
    p.add_argument("--from", dest="from_date", help="first session date (inclusive)")
    p.add_argument("--to", dest="to_date", help="last session date (inclusive)")
    p.add_argument("--params", help="JSON or @file")
    p.add_argument("--no-persist", action="store_true")
    p.add_argument("--allow-unready", action="store_true")
    p = sub.add_parser("backtest", help="backtest commands")
    bsub = p.add_subparsers(dest="bt_cmd", required=True)
    p = bsub.add_parser("run", help="run an engine over stored bars and print the metrics")
    p.add_argument("--engine", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--timeframe")
    p.add_argument("--from", dest="from_date")
    p.add_argument("--to", dest="to_date")
    p.add_argument("--mode", choices=["tv", "conservative"], default="tv")
    p.add_argument("--qty", type=float, default=1.0)
    p.add_argument("--cost-pts", type=float, default=0.0)
    p.add_argument("--params", help="JSON")
    sub.add_parser("kite-instruments", help="download and store the Kite instrument master")
    p = sub.add_parser("kite-backfill", help="fetch historical 1m candles from Kite")
    p.add_argument("--symbol", default="NIFTY 50")
    p.add_argument("--from", dest="from_date", required=True)
    p.add_argument("--to", dest="to_date", required=True)
    p = sub.add_parser("set-tick-size", help="set an instrument's tick size (user-provided fact)")
    p.add_argument("--instrument", default="kite:NSE:NIFTY 50")
    p.add_argument("--tick", type=float, required=True)
    p = sub.add_parser("kite-smoke", help="live check, run by you after Connect Kite")
    p.add_argument(
        "--probe-limits", action="store_true", help="also test the 60/61-day minute range"
    )
    p = sub.add_parser("research-counts", help="outcome counts per baseline x experiment")
    p.add_argument("--symbol", default="NIFTY 50")
    p = sub.add_parser(
        "demo-replay", help="replay the oracle sessions as live ticks (demo:NIFTY 50)"
    )
    p.add_argument("--speed", type=float, default=200.0, help="times real speed")
    p.add_argument("--max-sessions", type=int)
    p.add_argument("--from", dest="from_date", help="first session date")
    p.add_argument(
        "--exit-at-end", action="store_true", help="exit when the replay ends (default: hold)"
    )
    p = sub.add_parser("parity", help="compare an engine with TradingView golden / the oracle")
    p.add_argument("--engine", required=True)
    p.add_argument("--golden", help="dir with ohlc_plots.csv and trades.csv")
    p.add_argument("--oracle", help="twin trade log (default: reference/oracle/logs)")
    args = ap.parse_args(argv)
    if args.cmd == "hash-password":
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Repeat: ") or not pw:
            print("passwords differ or empty", file=sys.stderr)
            return 1
        # single-quoted: '$' would otherwise be interpolated by compose/dotenv
        print(f"APP_PASSWORD_HASH='{hash_password(pw)}'")
    elif args.cmd == "openapi":
        from nifty.api.main import create_app

        print(json.dumps(create_app().openapi()))
    elif args.cmd == "import-csv":
        return _import_csv(args)
    elif args.cmd == "bars":
        return _bars(args)
    elif args.cmd == "snapshot":
        return _snapshot(args)
    elif args.cmd == "run-engine":
        return _run_engine_cli(args)
    elif args.cmd == "backtest":
        return _backtest_cli(args)
    elif args.cmd == "kite-instruments":
        return _kite_instruments(args)
    elif args.cmd == "kite-backfill":
        return _kite_backfill(args)
    elif args.cmd == "set-tick-size":
        return _set_tick_size(args)
    elif args.cmd == "kite-smoke":
        return _kite_smoke(args)
    elif args.cmd == "research-counts":
        return _research_counts_cli(args)
    elif args.cmd == "research-counts":
        return _research_counts_cli(args)
    elif args.cmd == "demo-replay":
        return _demo_replay(args)
    elif args.cmd == "parity":
        return _parity(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
