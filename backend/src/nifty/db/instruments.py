import json

from sqlalchemy import Connection, text

from nifty.contracts import Instrument

_COLS = (
    "instrument_id provider provider_token exchange segment instrument_type tradingsymbol "
    "underlying expiry strike option_type tick_size lot_size currency metadata_version"
).split()


def upsert_instrument(conn: Connection, ins: Instrument) -> None:
    vals = {c: getattr(ins, c) for c in _COLS}
    vals["provider_meta"] = json.dumps(ins.provider_meta)
    cols = ", ".join([*_COLS, "provider_meta"])
    params = ", ".join([f":{c}" for c in _COLS] + ["CAST(:provider_meta AS jsonb)"])
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in [*_COLS[1:], "provider_meta"])
    conn.execute(
        text(
            f"INSERT INTO instruments ({cols}) VALUES ({params}) "
            f"ON CONFLICT (instrument_id) DO UPDATE SET {sets}"
        ),
        vals,
    )


def find_by_symbol(conn: Connection, symbol: str, provider: str | None = None) -> Instrument | None:
    row = (
        conn.execute(
            text(
                "SELECT *, provider_meta AS pm FROM instruments "
                "WHERE tradingsymbol = :s AND (CAST(:p AS text) IS NULL OR provider = :p) "
                "ORDER BY instrument_id LIMIT 1"
            ),
            {"s": symbol, "p": provider},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    data = {c: row[c] for c in _COLS}
    return Instrument(**data, provider_meta=row["pm"] or {})


def get_instrument(conn: Connection, instrument_id: str) -> Instrument | None:
    row = (
        conn.execute(
            text("SELECT *, provider_meta AS pm FROM instruments WHERE instrument_id = :i"),
            {"i": instrument_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return Instrument(**{c: row[c] for c in _COLS}, provider_meta=row["pm"] or {})


def find_instrument(conn: Connection, symbol: str) -> Instrument | None:
    """By exact instrument_id (kite:NSE:NIFTY 50, demo:NIFTY 50) or by trading symbol."""
    return get_instrument(conn, symbol) or find_by_symbol(conn, symbol)
