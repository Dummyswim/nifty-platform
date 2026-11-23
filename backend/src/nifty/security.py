"""Password hashing (stdlib scrypt) and signed session cookies."""

import base64
import hashlib
import hmac
import secrets
import time

N, R, P = 2**14, 8, 1
MAXMEM = 128 * N * R * 2 + 1024 * 1024
SESSION_TTL_S = 12 * 3600


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, maxmem=MAXMEM)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(h)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        want = _unb64(digest)
        got = hashlib.scrypt(
            password.encode(),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=128 * int(n) * int(r) * 2 + 1024 * 1024,
            dklen=len(want),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def sign_session(secret: str, now: float | None = None) -> str:
    exp = int((now if now is not None else time.time()) + SESSION_TTL_S)
    body = f"1.{exp}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_session(secret: str, token: str, now: float | None = None) -> int | None:
    """Return user_id for a valid, unexpired token, else None."""
    try:
        uid, exp, sig = token.split(".")
        want = hmac.new(secret.encode(), f"{uid}.{exp}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, want):
            return None
        if int(exp) < (now if now is not None else time.time()):
            return None
        return int(uid)
    except ValueError:
        return None
