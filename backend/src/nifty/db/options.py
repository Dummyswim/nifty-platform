"""Option data access: recorded quotes (ticks), coverage, OI series, index spot. Recorded data only
(D12): nothing here reconstructs a price."""

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from nifty.options.paper import Quote


class DbQuoteBook:
    """`QuoteBook` over the `ticks` table: the last recorded tick at or before a time."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self._cache: dict[tuple[str, datetime], Quote | None] = {}

    def last_quote(self, contract_id: str, at: datetime) -> Quote | None:
        key = (contract_id, at)
        if key not in self._cache:
            row = self.conn.execute(
                text(
                    "SELECT ts_exchange, bid, ask, ltp FROM ticks WHERE instrument_id = :c "
                    "AND ts_exchange <= :t ORDER BY ts_exchange DESC LIMIT 1"
                ),
                {"c": contract_id, "t": at},
            ).first()
            self._cache[key] = None if row is None else Quote(row[0], row[1], row[2], row[3])
        return self._cache[key]


def latest_ticks(conn: Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (instrument_id) instrument_id, ts_exchange, ltp, bid, ask, oi, "
            "volume_traded FROM ticks WHERE instrument_id = ANY(:ids) "
            "ORDER BY instrument_id, ts_exchange DESC"
        ),
        {"ids": ids},
    ).mappings()
    return {r["instrument_id"]: dict(r) for r in rows}


def coverage(conn: Connection, contract_id: str) -> dict[str, Any]:
    t = conn.execute(
        text(
            "SELECT count(*), min(ts_exchange), max(ts_exchange) FROM ticks WHERE instrument_id = :c"
        ),
        {"c": contract_id},
    ).one()
    nb = conn.execute(
        text("SELECT count(*) FROM bars WHERE instrument_id = :c AND timeframe = '1m'"),
        {"c": contract_id},
    ).scalar_one()
    return {
        "recorded": bool(t[0] or nb), "n_ticks": int(t[0]), "n_bars": int(nb),
        "first_tick": t[1], "last_tick": t[2],
    }  # fmt: skip


def oi_series(
    conn: Connection, contract_id: str, start: datetime | None, end: datetime | None
) -> tuple[list[int], list[float]]:  # fmt: skip
    """Last recorded open interest per minute."""
    rows = conn.execute(
        text(
            "SELECT date_trunc('minute', ts_exchange) AS m, "
            "(array_agg(oi ORDER BY ts_exchange DESC))[1] FROM ticks "
            "WHERE instrument_id = :c AND oi IS NOT NULL "
            "AND (CAST(:s AS timestamptz) IS NULL OR ts_exchange >= :s) "
            "AND (CAST(:e AS timestamptz) IS NULL OR ts_exchange < :e) GROUP BY m ORDER BY m"
        ),
        {"c": contract_id, "s": start, "e": end},
    ).all()
    return [int(r[0].timestamp()) for r in rows], [float(r[1]) for r in rows]


def spot(conn: Connection) -> tuple[float, datetime, str] | None:
    """Latest NIFTY 50 1m close: the Kite index when it has bars, else any NIFTY 50 index."""
    row = conn.execute(
        text(
            "SELECT b.close, b.bar_end_utc, b.instrument_id FROM bars b "
            "JOIN instruments i ON i.instrument_id = b.instrument_id "
            "WHERE i.tradingsymbol = 'NIFTY 50' AND i.instrument_type = 'INDEX' AND b.timeframe = '1m' "
            "ORDER BY (i.provider = 'kite') DESC, b.bar_start_utc DESC LIMIT 1"
        )
    ).first()
    return None if row is None else (float(row[0]), row[1], str(row[2]))
