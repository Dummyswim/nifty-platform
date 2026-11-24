"""Chart data access: columnar bars with a time cursor, drawings, prefs."""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from nifty.contracts import TF_MINUTES, Bar
from nifty.db.bars import read_bars
from nifty.marketdata.resample import resample
from nifty.timeutil import Calendar

SESSION_MIN = 375  # a 1d bucket spans one session of 1m bars
MAX_LIMIT = 20000


@dataclass
class BarsPage:
    t: list[int]
    o: list[float]
    h: list[float]
    l: list[float]  # noqa: E741
    c: list[float]
    v: list[float]
    flags: list[list[str]]
    volume_kind: str
    next_cursor: int | None


def _ratio(tf: str) -> int:
    return SESSION_MIN if tf == "1d" else TF_MINUTES[tf]


def bars_page(
    conn: Connection,
    instrument_id: str,
    tf: str,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    cursor: datetime | None,
    cal: Calendar,
) -> BarsPage:
    """Newest `limit` bars of [start, min(end, cursor)), ascending. Higher timeframes are resampled
    on the fly from stored 1m bars (cost grows with limit x bucket size; see STATE). `cursor` is an
    exclusive upper bound = `next_cursor` of the previous page (the oldest bar start returned)."""
    hi = min([x for x in (end, cursor) if x is not None], default=None)
    if tf == "1m":
        bars: list[Bar] = read_bars(conn, instrument_id, "1m", start, hi, last_n=limit + 1)
        more = len(bars) > limit
        bars = bars[-limit:]
    else:
        n = limit * _ratio(tf) + SESSION_MIN
        raw = read_bars(conn, instrument_id, "1m", start, hi, last_n=n)
        truncated = len(raw) == n
        bars = resample(raw, tf, cal)
        if truncated and bars:
            bars = bars[1:]  # oldest bucket may have lost 1m members to the read window
        more = truncated or len(bars) > limit
        bars = bars[-limit:]
    kinds = {b.volume_kind for b in bars}
    return BarsPage(
        t=[int(b.bar_start_utc.timestamp()) for b in bars],
        o=[b.open for b in bars],
        h=[b.high for b in bars],
        l=[b.low for b in bars],
        c=[b.close for b in bars],
        v=[b.volume for b in bars],
        flags=[list(b.quality_flags) for b in bars],
        volume_kind=kinds.pop() if len(kinds) == 1 else ("exchange" if kinds else "absent"),
        next_cursor=int(bars[0].bar_start_utc.timestamp()) if bars and more else None,
    )


def list_instruments(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT instrument_id, tradingsymbol, instrument_type, tick_size, lot_size "
            "FROM instruments i WHERE i.instrument_type NOT IN ('CE', 'PE') "
            "AND EXISTS (SELECT 1 FROM bars b WHERE b.instrument_id = i.instrument_id) "
            "ORDER BY tradingsymbol, instrument_id"
        )
    ).mappings()
    return [dict(r) for r in rows]


# ---- drawings ----------------------------------------------------------------------------------
def list_drawings(conn: Connection, instrument_id: str, user_id: int = 1) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, kind, data FROM drawings WHERE user_id = :u AND instrument_id = :i "
            "ORDER BY created_at, id"
        ),
        {"u": user_id, "i": instrument_id},
    ).mappings()
    return [dict(r) for r in rows]


def create_drawing(
    conn: Connection, instrument_id: str, kind: str, data: dict[str, Any], user_id: int = 1
) -> str:
    did = "drw_" + uuid.uuid4().hex[:16]
    conn.execute(
        text(
            "INSERT INTO drawings (id, user_id, instrument_id, kind, data) "
            "VALUES (:id, :u, :i, :k, CAST(:d AS jsonb))"
        ),
        {"id": did, "u": user_id, "i": instrument_id, "k": kind, "d": json.dumps(data)},
    )
    return did


def update_drawing(conn: Connection, did: str, data: dict[str, Any], user_id: int = 1) -> bool:
    return (
        conn.execute(
            text(
                "UPDATE drawings SET data = CAST(:d AS jsonb), updated_at = now() "
                "WHERE id = :id AND user_id = :u"
            ),
            {"id": did, "u": user_id, "d": json.dumps(data)},
        ).rowcount
        > 0
    )


def delete_drawing(conn: Connection, did: str, user_id: int = 1) -> bool:
    return (
        conn.execute(
            text("DELETE FROM drawings WHERE id = :id AND user_id = :u"), {"id": did, "u": user_id}
        ).rowcount
        > 0
    )


# ---- prefs -------------------------------------------------------------------------------------
def get_prefs(conn: Connection, user_id: int = 1) -> dict[str, Any]:
    rows = conn.execute(text("SELECT key, value FROM prefs WHERE user_id = :u"), {"u": user_id})
    return {r[0]: r[1] for r in rows}


def set_pref(conn: Connection, key: str, value: Any, user_id: int = 1) -> None:
    conn.execute(
        text(
            "INSERT INTO prefs (user_id, key, value) VALUES (:u, :k, CAST(:v AS jsonb)) "
            "ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
        ),
        {"u": user_id, "k": key, "v": json.dumps(value)},
    )
