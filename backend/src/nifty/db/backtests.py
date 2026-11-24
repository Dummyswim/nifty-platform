"""Backtest = engine over a snapshot -> persisted run + trades + summary (D07, C04)."""

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, text

from nifty.analytics.export import STOP_REASONS, TARGET_REASONS
from nifty.analytics.metrics import compute_metrics
from nifty.contracts import Bar, Instrument, TradeRecord
from nifty.db.bars import create_snapshot, read_bars
from nifty.db.instruments import find_instrument, get_instrument
from nifty.db.runs import load_events, persist_run, run_key
from nifty.engines.base import get_engine, load_builtin_engines
from nifty.engines.runner import RunResult, run_batch
from nifty.marketdata.resample import resample
from nifty.timeutil import Calendar


class BacktestError(ValueError):
    """User-level failure (bad payload, missing data); its message is stored on the job."""


def _range(cal: Calendar, f: str | None, t: str | None) -> tuple[datetime | None, datetime | None]:
    lo = cal.session_bounds(date.fromisoformat(f))[0] if f else None
    hi = cal.session_bounds(date.fromisoformat(t))[1] if t else None
    return lo, hi


def resolve_input(
    conn: Connection, p: dict[str, Any], cal: Calendar
) -> tuple[Instrument, list[Bar], str]:
    """(instrument, 1m bars, snapshot_id) from `snapshot_id` or `symbol` + optional dates."""
    if p.get("snapshot_id"):
        row = (
            conn.execute(
                text("SELECT instrument_id, from_utc, to_utc FROM datasets WHERE snapshot_id = :s"),
                {"s": p["snapshot_id"]},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise BacktestError(f"unknown snapshot {p['snapshot_id']}")
        ins = get_instrument(conn, row["instrument_id"])
        lo, hi = row["from_utc"], row["to_utc"]
    else:
        ins = find_instrument(conn, p.get("symbol") or "")
        lo, hi = _range(cal, p.get("from_date"), p.get("to_date"))
    if ins is None:
        raise BacktestError("unknown symbol; import data first")
    bars = read_bars(conn, ins.instrument_id, "1m", lo, hi)
    if not bars:
        raise BacktestError("no 1m bars in range")
    if not p.get("snapshot_id"):  # same bounds as `nifty.cli snapshot` / run-engine
        first = cal.session_date(bars[0].bar_start_utc).isoformat()
        last = cal.session_date(bars[-1].bar_start_utc).isoformat()
        start, end = _range(cal, p.get("from_date") or first, p.get("to_date") or last)
        assert start is not None and end is not None
        lo, hi = start, end
    snap = create_snapshot(conn, ins.instrument_id, "1m", lo, hi)
    return ins, bars, snap.snapshot_id


def _apply_mode(r: RunResult, mode: str, qty: float, cost_pts: float) -> list[TradeRecord]:
    if mode not in ("tv", "conservative"):
        raise BacktestError(f"unknown mode {mode!r}")
    if r.engine_id.startswith("pine.") and mode != "tv":
        raise BacktestError("Pine ports run in tv mode (spec/03)")
    out = []
    for t in r.trades:
        upd: dict[str, Any] = {"qty": qty}
        if mode == "conservative" and cost_pts:
            upd["cost_pts"] = cost_pts
            upd["net_pts"] = t.gross_pts - cost_pts
        out.append(t.model_copy(update=upd))
    return out


def map_option_trades(
    conn: Connection, trades: list[TradeRecord], policy: dict[str, Any]
) -> tuple[list[TradeRecord], dict[str, Any]]:
    """CE/PE paper mapping on recorded quotes only (D12). Unmapped trades stay index-only and are
    counted (`no_quote`, `no_contract`)."""
    from nifty.db.chart import get_prefs
    from nifty.db.instruments import option_instruments
    from nifty.db.options import DbQuoteBook
    from nifty.options.chain import DEFAULT_OFFSETS
    from nifty.options.paper import Policy, map_trade

    prefs = get_prefs(conn)
    saved = prefs.get("options.strike_offsets") or {}
    offsets = {**DEFAULT_OFFSETS, **{k: int(v) for k, v in saved.items() if k in DEFAULT_OFFSETS}}
    try:
        pol = Policy(**policy)
    except TypeError as e:
        raise BacktestError(f"bad option_policy: {e}") from e
    options, book = option_instruments(conn), DbQuoteBook(conn)
    out: list[TradeRecord] = []
    counts = {"no_quote": 0, "no_contract": 0}
    for t in trades:
        m, why = map_trade(t, options, book, pol, offsets)
        out.append(m or t)
        if why:
            counts[why] += 1
    mapped = [t for t in out if t.contract_id]
    return out, {
        "policy": policy, "n_mapped": len(mapped), "no_quote": counts["no_quote"],
        "no_contract": counts["no_contract"], "cost_inr": pol.cost_inr,
        "total_pnl_inr": sum(t.pnl_inr or 0.0 for t in mapped),
    }  # fmt: skip


def run_backtest(conn: Connection, p: dict[str, Any]) -> str:
    """Returns backtest_id. Same engine/params/snapshot/timeframe/mode/qty/cost => same id."""
    load_builtin_engines()
    mode, qty, cost = p.get("mode", "tv"), float(p.get("qty", 1.0)), float(p.get("cost_pts", 0.0))
    if mode == "tv" and cost:
        raise BacktestError("cost_pts applies to conservative mode; tv uses the engine commission")
    if qty <= 0 or cost < 0:
        raise BacktestError("qty must be > 0 and cost_pts >= 0")
    cal = Calendar.load()
    ins, bars, snapshot_id = resolve_input(conn, p, cal)
    try:
        spec = get_engine(p["engine_id"])
    except KeyError as e:
        raise BacktestError(f"unknown engine {p['engine_id']!r}") from e
    tf = p.get("timeframe") or spec.cls.default_timeframe
    r = run_batch(
        p["engine_id"], p.get("params") or {}, bars, tf, instrument=ins, calendar=cal,
        source_id=snapshot_id,
    )  # fmt: skip
    trades = _apply_mode(r, mode, qty, cost)
    policy = p.get("option_policy")
    option_summary: dict[str, Any] | None = None
    if policy:
        trades, option_summary = map_option_trades(conn, trades, policy)
    run_id, _ = persist_run(conn, r)
    pol_key = json.dumps(policy, sort_keys=True) if policy else ""
    bt_id = (
        "bt_"
        + hashlib.sha256(f"{run_key(r)}|{mode}|{qty}|{cost}|{pol_key}".encode()).hexdigest()[:16]
    )
    sessions = {cal.session_date(b.bar_start_utc) for b in bars}
    summary = compute_metrics(trades, cal.session_date, sessions)
    summary["option"] = option_summary
    got = conn.execute(
        text(
            "INSERT INTO backtests (backtest_id, run_id, engine_id, instrument_id, snapshot_id, "
            "timeframe, mode, qty, cost_pts, params, summary) VALUES (:b, :r, :e, :i, :s, :tf, :m, "
            ":q, :c, CAST(:p AS jsonb), CAST(:sum AS jsonb)) ON CONFLICT DO NOTHING RETURNING 1"
        ),
        {
            "b": bt_id, "r": run_id, "e": r.engine_id, "i": ins.instrument_id, "s": snapshot_id,
            "tf": tf, "m": mode, "q": qty, "c": cost, "p": json.dumps(r.params),
            "sum": json.dumps(summary, allow_nan=False),
        },
    ).first()  # fmt: skip
    if got is not None and trades:
        conn.execute(
            text(
                "INSERT INTO trades (backtest_id, ord, trade_id, side, signal_bar_start, entry_time, "
                "exit_time, entry_px, exit_px, exit_reason, net_pts, trade) VALUES (:b, :o, :id, "
                ":sd, :sb, :et, :xt, :ep, :xp, :xr, :n, CAST(:t AS jsonb))"
            ),
            [
                {
                    "b": bt_id, "o": i, "id": t.trade_id, "sd": t.side, "sb": t.signal_bar_start,
                    "et": t.entry_time, "xt": t.exit_time, "ep": t.entry_px, "xp": t.exit_px,
                    "xr": t.exit_reason, "n": t.net_pts, "t": t.model_dump_json(),
                }
                for i, t in enumerate(trades)
            ],
        )  # fmt: skip
    return bt_id


def load_trades(conn: Connection, bt_id: str) -> list[TradeRecord]:
    rows = conn.execute(
        text("SELECT trade FROM trades WHERE backtest_id = :b ORDER BY ord"), {"b": bt_id}
    )
    return [TradeRecord.model_validate(r[0]) for r in rows]


def get_backtest(conn: Connection, bt_id: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT backtest_id, run_id, engine_id, instrument_id, snapshot_id, timeframe, mode, "
                "qty, cost_pts, params, summary, created_at FROM backtests WHERE backtest_id = :b"
            ),
            {"b": bt_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def list_backtests(conn: Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT backtest_id, engine_id, instrument_id, snapshot_id, timeframe, mode, created_at, "
            "summary->>'n_trades' AS n_trades, summary->>'total_pnl_pts' AS total_pnl_pts "
            "FROM backtests ORDER BY created_at DESC LIMIT :n"
        ),
        {"n": limit},
    ).mappings()
    return [dict(r) for r in rows]


def audit_trade(
    conn: Connection, bt_id: str, trade_id: str, window: int = 10
) -> dict[str, Any] | None:
    """Everything the audit view needs (webapp L246-264). Strike/option fields are null for index
    trades; levels come from the engine's `signal` event of the trade's signal bar."""
    bt = get_backtest(conn, bt_id)
    trade = next((t for t in load_trades(conn, bt_id) if t.trade_id == trade_id), None)
    if bt is None or trade is None:
        return None
    ins = get_instrument(conn, bt["instrument_id"])
    assert ins is not None
    tf_min = {"1m": 1, "5m": 5, "15m": 15}.get(bt["timeframe"], 1)
    pad = timedelta(minutes=tf_min * window)
    lo = (trade.signal_bar_start or trade.entry_time) - pad
    hi = trade.exit_time + pad
    cal = Calendar.load()
    bars = resample(read_bars(conn, ins.instrument_id, "1m", lo, hi), bt["timeframe"], cal)
    win = [
        {"t": b.bar_start_utc, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
        for b in bars
        if b.finalized
    ]
    events = [
        e.model_dump(mode="json")
        for e in load_events(conn, bt["run_id"])
        if lo <= e.bar_start_utc <= hi
    ]
    sig = next(
        (
            e.payload
            for e in load_events(conn, bt["run_id"])
            if e.event_type == "signal" and e.bar_start_utc == trade.signal_bar_start
        ),
        {},
    )
    return {
        "trade": trade.model_dump(mode="json"),
        "levels": {
            "entry_px_pts": trade.entry_px,
            "stop_px_pts": sig.get("stop"),
            "target_px_pts": sig.get("target"),
            "exit_px_pts": trade.exit_px,
        },
        "strike": None,
        "option_type": None,
        "pnl_pts": trade.net_pts,
        "pnl_inr": trade.pnl_inr,
        "roi_pct": trade.roi_pct,
        "stop_hit": trade.exit_reason in STOP_REASONS,
        "target_hit": trade.exit_reason in TARGET_REASONS,
        "exit_reason": trade.exit_reason,
        "window_bars": win,
        "events": events,
    }
