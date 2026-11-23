"""Kite persistence: versioned instrument master, encrypted token, authenticated client factory."""

import csv
import gzip
import hashlib
import io
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, text

from nifty.config import Settings
from nifty.contracts import Instrument
from nifty.db.instruments import upsert_instrument
from nifty.marketdata.base import ErrorCode, ProviderError
from nifty.marketdata.kite.client import KiteClient
from nifty.marketdata.kite.master import parse_master
from nifty.marketdata.kite.tokens import (
    TokenDecryptError,
    decrypt_token,
    encrypt_token,
    next_expiry,
)
from nifty.timeutil import utcnow

STATUS_TTL = timedelta(minutes=5)  # /user/profile validation at most this often


# ---- token ------------------------------------------------------------------------------------
def store_token(
    conn: Connection, secret: str, token: str, kite_user: str, now: datetime | None = None
) -> datetime:
    now = now or utcnow()
    exp = next_expiry(now)
    conn.execute(
        text(
            "INSERT INTO kite_tokens (user_id, ciphertext, kite_user_id, created_at, expires_at, "
            "validated_at, last_error) VALUES (1, :c, :u, :n, :e, :n, NULL) "
            "ON CONFLICT (user_id) DO UPDATE SET ciphertext = :c, kite_user_id = :u, created_at = :n, "
            "expires_at = :e, validated_at = :n, last_error = NULL"
        ),
        {"c": encrypt_token(secret, token), "u": kite_user, "n": now, "e": exp},
    )
    return exp


def load_token(conn: Connection, secret: str, now: datetime | None = None) -> str | None:
    """The decrypted token, or None when missing/expired. Never logged or returned by the API."""
    row = conn.execute(
        text("SELECT ciphertext, expires_at FROM kite_tokens WHERE user_id = 1")
    ).first()
    if row is None or row[1] <= (now or utcnow()):
        return None
    try:
        return decrypt_token(secret, row[0])
    except TokenDecryptError:
        return None


def client_for(conn: Connection, settings: Settings) -> KiteClient:
    """Authenticated client from the stored token; AUTH_EXPIRED when there is none."""
    token = load_token(conn, settings.app_secret_key)
    if not settings.kite_api_key:
        raise ProviderError(ErrorCode.AUTH_EXPIRED, "KITE_API_KEY is not set in .env")
    if token is None:
        raise ProviderError(
            ErrorCode.AUTH_EXPIRED, "Kite is not connected (token missing or expired)"
        )
    return KiteClient(settings.kite_api_key, settings.kite_api_secret, token)


def kite_status(
    conn: Connection, settings: Settings, now: datetime | None = None
) -> dict[str, Any]:
    """{connected, user_id, expires_at, last_error, instruments_updated_at}; validates the token
    with /user/profile at most every 5 minutes. No secret is ever included."""
    now = now or utcnow()
    row = conn.execute(
        text(
            "SELECT kite_user_id, expires_at, validated_at, last_error FROM kite_tokens WHERE user_id = 1"
        )
    ).first()
    master = conn.execute(text("SELECT max(fetched_at), count(*) FROM instrument_masters")).first()
    out: dict[str, Any] = {
        "connected": False, "user_id": None, "expires_at": None, "last_error": None,
        "instruments_updated_at": master[0] if master else None,
        "configured": bool(settings.kite_api_key and settings.kite_api_secret),
    }  # fmt: skip
    if row is None:
        return out
    out.update(user_id=row[0], expires_at=row[1], last_error=row[3])
    if row[1] <= now:
        out["last_error"] = "token expired (06:00 IST): connect Kite again"
        return out
    if row[2] is None or now - row[2] >= STATUS_TTL:
        try:
            client = client_for(conn, settings)
            client.profile()
            err = None
        except ProviderError as e:
            err = str(e)
        conn.execute(
            text("UPDATE kite_tokens SET validated_at = :n, last_error = :e WHERE user_id = 1"),
            {"n": now, "e": err},
        )
        out["last_error"] = err
    out["connected"] = out["last_error"] is None
    return out


# ---- instrument master ------------------------------------------------------------------------
def save_master(
    conn: Connection, csv_text: str, day: date | None = None
) -> tuple[str, list[Instrument]]:
    """Store the dump as a new version (date + sha256) and upsert the instruments we use."""
    day = day or utcnow().date()
    sha = hashlib.sha256(csv_text.encode()).hexdigest()
    version = f"{day.isoformat()}_{sha[:12]}"
    ins = parse_master(csv_text, version)
    n_rows = sum(1 for _ in csv.reader(io.StringIO(csv_text))) - 1
    conn.execute(
        text(
            "INSERT INTO instrument_masters (version, sha256, n_rows, n_used, content) "
            "VALUES (:v, :s, :n, :u, :c) ON CONFLICT (version) DO NOTHING"
        ),
        {"v": version, "s": sha, "n": n_rows, "u": len(ins), "c": gzip.compress(csv_text.encode())},
    )
    for i in ins:
        upsert_instrument(conn, i)
    return version, ins


def kite_instruments(conn: Connection) -> list[Instrument]:
    from nifty.db.instruments import get_instrument

    ids = conn.execute(
        text("SELECT instrument_id FROM instruments WHERE provider = 'kite'")
    ).scalars()
    return [i for x in ids if (i := get_instrument(conn, x)) is not None]
