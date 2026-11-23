"""Loaders: TradingView "Export chart data", "List of trades", and the Python-twin trade log."""

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nifty.contracts import Bar
from nifty.timeutil import IST

NAN = float("nan")


@dataclass(frozen=True)
class RefTrade:
    side: str  # long | short
    entry_time: datetime  # fill bar start (UTC)
    entry_px: float
    exit_time: datetime  # as the source reports it (bar start for TV; see oracle notes)
    exit_px: float
    reason: str
    pnl: float | None = None


def parse_time(raw: str) -> datetime:
    """ISO (with or without offset; naive = IST, the exchange timezone) or unix seconds/ms."""
    raw = raw.strip()
    if raw.lstrip("-").replace(".", "", 1).isdigit():
        v = float(raw)
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, UTC)
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T", 1))
    return (dt.replace(tzinfo=IST) if dt.tzinfo is None else dt).astimezone(UTC)


def _num(x: str | None) -> float:
    try:
        return float((x or "").replace(",", "").strip())
    except ValueError:
        return NAN


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip(): v for k, v in r.items()} for r in csv.DictReader(f)]


def load_tv_ohlc_plots(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Rows keyed by TradingView column title plus the plot column titles (not time/OHLC)."""
    rows = read_rows(path)
    base = {"time", "open", "high", "low", "close", "volume"}
    cols = [c for c in (rows[0] if rows else {}) if c.lower() not in base]
    return rows, cols


def tv_bars(rows: list[dict[str, str]], instrument_id: str, tf: str = "5m") -> list[Bar]:
    mins = {"1m": 1, "5m": 5, "15m": 15}[tf]
    out = []
    for r in rows:
        low = {k.lower(): v for k, v in r.items()}
        start = parse_time(low["time"])
        vol = _num(low.get("volume"))
        has_vol = vol == vol and vol > 0
        out.append(
            Bar(
                instrument_id=instrument_id, provider="csv", timeframe=tf,  # type: ignore[arg-type]
                bar_start_utc=start,
                bar_end_utc=datetime.fromtimestamp(start.timestamp() + mins * 60, UTC),
                open=_num(low["open"]), high=_num(low["high"]), low=_num(low["low"]),
                close=_num(low["close"]), volume=vol if has_vol else 0.0,
                volume_kind="exchange" if has_vol else "absent",
                received_at_utc=start,
            )
        )  # fmt: skip
    return out


def _col(row: dict[str, str], *names: str) -> str | None:
    for k, v in row.items():
        if any(k.lower().startswith(n) for n in names):
            return v
    return None


def load_tv_trades(path: Path) -> list[RefTrade]:
    """TradingView "List of trades": two rows per trade (Entry / Exit), paired by Trade #."""
    by_no: dict[str, dict[str, dict[str, str]]] = {}
    for r in read_rows(path):
        no = _col(r, "trade #", "trade") or ""
        typ = (_col(r, "type") or "").lower()
        by_no.setdefault(no, {})["entry" if typ.startswith("entry") else "exit"] = r
    out = []
    for no in sorted(by_no, key=lambda x: int(x) if x.isdigit() else 0):
        e, x = by_no[no].get("entry"), by_no[no].get("exit")
        if e is None or x is None:
            continue  # open trade at the end of the data
        side = "long" if "long" in (_col(e, "type") or "").lower() else "short"
        out.append(
            RefTrade(
                side, parse_time(_col(e, "date") or ""), _num(_col(e, "price")),
                parse_time(_col(x, "date") or ""), _num(_col(x, "price")),
                (_col(x, "signal") or "").strip(), _num(_col(x, "net p&l", "profit", "p&l")),
            )
        )  # fmt: skip
    return out


def load_oracle_trades(path: Path) -> list[RefTrade]:
    """`reference/oracle/logs/scalper_trades.csv`: entry_ts = FILL bar start, exit_ts = the bar
    that triggered the exit (start) except SESSION_END/EOD, which the twin stamps at the bar start
    of the signalling bar too. `net_pts` is pts after the twin's costBps."""
    return [
        RefTrade(
            "long" if r["side"] == "BUY" else "short",
            parse_time(r["entry_ts"]), _num(r["entry"]),
            parse_time(r["exit_ts"]), _num(r["exit"]), r["reason"], _num(r["net_pts"]),
        )
        for r in read_rows(path)
    ]  # fmt: skip
