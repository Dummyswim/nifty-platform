"""SYNTHETIC options fixture: `seed(conn, now)` writes a NIFTY 50 index, CE/PE contracts for three
weekly expiries and one monthly, a few 1m bars and quote ticks (bid/ask/ltp/oi). Test/e2e use only."""

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "src"))

from sqlalchemy import Connection, text  # noqa: E402

from nifty.contracts import Bar, Instrument  # noqa: E402
from nifty.db.bars import upsert_bars  # noqa: E402
from nifty.db.instruments import upsert_instrument  # noqa: E402
from nifty.options.bs import bs, effective_today, years_to_expiry  # noqa: E402

STEP, N_STRIKES, BASE = 50.0, 13, 24_700.0  # strikes 24700 .. 25300
SPOT = 25_020.0  # ATM = 25000
IDX = "kite:NSE:NIFTY 50"
TOKEN0 = 9_000_000


def expiries(today: date) -> list[date]:
    """Three weekly Tuesdays on/after today and the last Tuesday of the following month."""
    first = today + timedelta(days=(1 - today.weekday()) % 7)
    weeks = [first + timedelta(days=7 * i) for i in range(3)]
    nxt = (first.replace(day=1) + timedelta(days=40)).replace(day=1)
    end = (nxt.replace(day=28) + timedelta(days=10)).replace(day=1) - timedelta(days=1)
    monthly = end - timedelta(days=(end.weekday() - 1) % 7)
    return sorted({*weeks, monthly})


def contracts(today: date) -> list[Instrument]:
    out, tok = [], TOKEN0
    for e in expiries(today):
        for i in range(N_STRIKES):
            k = BASE + STEP * i
            for t in ("CE", "PE"):
                tok += 1
                sym = f"NIFTYDEMO{e:%y%m%d}{int(k)}{t}"
                out.append(
                    Instrument(
                        instrument_id=f"kite:NFO:{sym}", provider="kite", provider_token=tok,
                        exchange="NFO", segment="NFO-OPT", instrument_type=t,  # type: ignore[arg-type]
                        tradingsymbol=sym, underlying="NIFTY", expiry=e, strike=k, option_type=t,  # type: ignore[arg-type]
                        tick_size=0.05, lot_size=75, metadata_version="synthetic-demo",
                        provider_meta={"synthetic": True},
                    )
                )  # fmt: skip
    return out


def seed(conn: Connection, now: datetime | None = None) -> dict[str, object]:
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    today = effective_today(now)
    upsert_instrument(
        conn,
        Instrument(
            instrument_id=IDX, provider="kite", provider_token=256265, exchange="NSE", segment="INDICES",
            instrument_type="INDEX", tradingsymbol="NIFTY 50", tick_size=0.05, metadata_version="synthetic-demo",
            provider_meta={"synthetic": True},
        ),
    )  # fmt: skip
    minute = now.replace(second=0) - timedelta(minutes=1)
    upsert_bars(
        conn,
        [
            Bar(
                instrument_id=IDX, provider="kite", timeframe="1m",
                bar_start_utc=minute - timedelta(minutes=i), bar_end_utc=minute - timedelta(minutes=i - 1),
                open=SPOT, high=SPOT + 2, low=SPOT - 2, close=SPOT, volume=0.0, volume_kind="absent",
                received_at_utc=now,
            )
            for i in range(5)
        ],
    )  # fmt: skip
    cs = contracts(today)
    for c in cs:
        upsert_instrument(conn, c)
    ticks, bars = [], []
    for c in cs:
        if c.expiry not in expiries(today)[:2]:  # recorded: the two nearest expiries only
            continue
        assert c.strike is not None and c.expiry is not None
        g = bs(
            SPOT,
            c.strike,
            max(years_to_expiry(c.expiry, now), 1e-4),
            0.065,
            0.15,
            c.option_type == "CE",
        )
        px = max(g.price if g else 0.1, 0.1)
        for i, secs in enumerate((120, 60, 5)):  # ticks 2 min, 1 min and 5 s ago
            ts = now - timedelta(seconds=secs)
            ltp = round(px + i * 0.05, 2)
            ticks.append({"i": c.instrument_id, "te": ts, "tr": ts, "ltp": ltp, "v": 100.0 * (i + 1),
                          "oi": 1_000.0 + 10 * i, "b": round(ltp - 0.5, 2), "a": round(ltp + 0.5, 2),
                          "bq": 75.0, "aq": 75.0})  # fmt: skip
        if c.strike in (25_000.0, 25_050.0, 24_950.0) and c.expiry == expiries(today)[0]:
            for j in range(3):
                bars.append(
                    Bar(
                        instrument_id=c.instrument_id, provider="kite", timeframe="1m",
                        bar_start_utc=minute - timedelta(minutes=2 - j), bar_end_utc=minute - timedelta(minutes=1 - j),
                        open=px, high=px + 1, low=px - 1, close=px + 0.1 * j, volume=100.0 * (j + 1),
                        volume_kind="exchange", received_at_utc=now,
                    )
                )  # fmt: skip
    conn.execute(
        text(
            "INSERT INTO ticks (instrument_id, ts_exchange, ts_received, ltp, volume_traded, oi, bid, ask, "
            "bid_qty, ask_qty) VALUES (:i, :te, :tr, :ltp, :v, :oi, :b, :a, :bq, :aq)"
        ),
        ticks,
    )
    upsert_bars(conn, bars)
    return {
        "expiries": expiries(today),
        "n_contracts": len(cs),
        "n_ticks": len(ticks),
        "n_bars": len(bars),
    }
