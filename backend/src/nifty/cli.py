import argparse
import getpass
import json
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Connection

from nifty.contracts import TF_MINUTES, Instrument
from nifty.security import hash_password
from nifty.timeutil import Calendar, to_ist


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
