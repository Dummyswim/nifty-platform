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

    cal = Calendar.load()
    start = cal.session_bounds(date.fromisoformat(a.from_date))[0]
    end = cal.session_bounds(date.fromisoformat(a.to_date))[1]
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
