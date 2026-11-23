"""Access-token encryption: Fernet with a key derived (HKDF-SHA256) from APP_SECRET_KEY (D19)."""

import base64
from datetime import datetime, time, timedelta

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from nifty.timeutil import IST


class TokenDecryptError(Exception):
    pass


def _fernet(secret: str) -> Fernet:
    if not secret:
        raise TokenDecryptError("APP_SECRET_KEY is not set")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"nifty-kite-token").derive(
        secret.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_token(secret: str, token: str) -> bytes:
    return _fernet(secret).encrypt(token.encode())


def decrypt_token(secret: str, blob: bytes) -> str:
    try:
        return _fernet(secret).decrypt(bytes(blob)).decode()
    except InvalidToken as e:
        raise TokenDecryptError("stored token cannot be decrypted with this APP_SECRET_KEY") from e


def next_expiry(now: datetime) -> datetime:
    """Kite tokens expire at 06:00 IST the next day: the first 06:00 IST strictly after `now`."""
    local = now.astimezone(IST)
    cand = datetime.combine(local.date(), time(6, 0), tzinfo=IST)
    if cand <= local:
        cand += timedelta(days=1)
    return cand.astimezone(now.tzinfo)
