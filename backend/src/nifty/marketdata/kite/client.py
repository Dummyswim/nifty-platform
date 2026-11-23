"""Read-only Kite Connect REST client (D19/D28, facts in docs/spec/08-kite-verified.md).

Only an allowlist of (method, path) can be called; anything else raises `ForbiddenEndpoint` before
any I/O. Secrets (api_secret, access_token, request_token, checksum, Authorization) never appear in
logs, exception messages or reprs.
"""

import gzip
import hashlib
import logging
import random
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from nifty.marketdata.base import ErrorCode, ProviderError
from nifty.timeutil import IST

log = logging.getLogger("nifty.kite")
BASE_URL = "https://api.kite.trade"
LOGIN_URL = "https://kite.zerodha.com/connect/login"
INTERVALS = ("minute", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute", "day")

ALLOWLIST: list[tuple[str, re.Pattern[str]]] = [
    ("POST", re.compile(r"^/session/token$")),
    ("GET", re.compile(r"^/user/profile$")),
    ("GET", re.compile(r"^/instruments$")),
    ("GET", re.compile(r"^/instruments/[A-Z]{2,6}$")),
    ("GET", re.compile(rf"^/instruments/historical/\d+/({'|'.join(INTERVALS)})$")),
    ("GET", re.compile(r"^/quote$")),
    ("GET", re.compile(r"^/quote/(ltp|ohlc)$")),
]
# requests per second (verified: /exceptions/)
RATES = {"historical": 3.0, "quote": 1.0, "other": 10.0}


class ForbiddenEndpoint(Exception):
    pass


def bucket_of(path: str) -> str:
    if path.startswith("/instruments/historical/"):
        return "historical"
    return "quote" if path.startswith("/quote") else "other"


class RateLimiter:
    """Token bucket per endpoint class (burst 1). Clock and sleep are injectable."""

    def __init__(
        self,
        rates: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rates = rates or RATES
        self.clock, self.sleep = clock, sleep
        self._next: dict[str, float] = {}

    def acquire(self, bucket: str) -> None:
        now = self.clock()
        ready = self._next.get(bucket, now)
        if ready > now:
            self.sleep(ready - now)
            now = ready
        self._next[bucket] = max(now, ready) + 1.0 / self.rates[bucket]


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    return hashlib.sha256((api_key + request_token + api_secret).encode()).hexdigest()


def map_error(status: int, body: Any) -> ProviderError:
    """HTTP status + Kite error body -> our taxonomy (spec/08)."""
    et = body.get("error_type", "") if isinstance(body, dict) else ""
    msg = str(body.get("message", "")) if isinstance(body, dict) else ""
    low = msg.lower()
    if et == "TokenException" or status == 403:
        code = ErrorCode.AUTH_EXPIRED
    elif status == 429:
        code = ErrorCode.RATE_LIMITED
    elif et == "PermissionException" or "subscription" in low or "not enabled" in low:
        code = ErrorCode.ENTITLEMENT
    elif status >= 500 or et in ("NetworkException", "GeneralException") and status >= 500:
        code = ErrorCode.NETWORK
    else:
        code = ErrorCode.BAD_DATA
    return ProviderError(code, f"HTTP {status} {et or 'error'}: {msg or 'no message'}")


class KiteClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str = "",
        access_token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = BASE_URL,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 3,
        timeout: float = 20.0,
    ) -> None:
        self._key, self._secret, self._token = api_key, api_secret, access_token
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)
        self.limiter = limiter or RateLimiter(sleep=sleep)
        self._sleep, self._max_retries = sleep, max_retries

    def __repr__(self) -> str:
        return f"KiteClient(authenticated={self._token is not None})"

    def _redact(self, text: str) -> str:
        for s in (self._secret, self._token):
            if s:
                text = text.replace(s, "***")
        text = re.sub(r"(access_token|request_token|api_secret|checksum)=[^&\s]+", r"\1=***", text)
        return re.sub(r"(?i)authorization['\": ]+token [^\s'\",]+", "authorization: ***", text)

    def set_token(self, token: str | None) -> None:
        self._token = token

    # ---- transport ----------------------------------------------------------------------------
    def _request(
        self, method: str, path: str, *, params: Any = None,
        data: dict[str, str] | None = None, auth: bool = True,
    ) -> httpx.Response:  # fmt: skip
        if not any(m == method and p.match(path) for m, p in ALLOWLIST):
            raise ForbiddenEndpoint(f"{method} {path} is not on the read-only allowlist")
        headers = {"X-Kite-Version": "3"}
        if auth:
            if not self._token:
                raise ProviderError(ErrorCode.AUTH_EXPIRED, "no access token; connect Kite")
            headers["Authorization"] = f"token {self._key}:{self._token}"
        last: ProviderError | None = None
        for attempt in range(self._max_retries + 1):
            self.limiter.acquire(bucket_of(path))
            try:
                res = self._http.request(method, path, params=params, data=data, headers=headers)
            except httpx.HTTPError as e:
                last = ProviderError(ErrorCode.NETWORK, self._redact(f"{type(e).__name__}: {e}"))
            else:
                if res.status_code < 400:
                    return res
                try:
                    body = res.json()
                except ValueError:
                    body = {}
                last = map_error(res.status_code, body)
                last = ProviderError(last.code, self._redact(str(last).split(": ", 1)[1]))
            if (
                last.code not in (ErrorCode.NETWORK, ErrorCode.RATE_LIMITED)
                or attempt == self._max_retries
            ):
                break
            delay = 0.5 * 2**attempt + random.random() * 0.25
            log.warning(
                "kite %s %s: %s; retry %d in %.1fs", method, path, last.code, attempt + 1, delay
            )
            self._sleep(delay)
        assert last is not None
        log.warning("kite %s %s failed: %s", method, path, last)
        raise last

    def _json(self, res: httpx.Response) -> Any:
        try:
            body = res.json()
        except ValueError as e:
            raise ProviderError(ErrorCode.BAD_DATA, "response is not JSON") from e
        if not isinstance(body, dict) or body.get("status") != "success":
            raise ProviderError(ErrorCode.BAD_DATA, "unexpected response envelope")
        return body.get("data")

    # ---- login --------------------------------------------------------------------------------
    def login_url(self) -> str:
        return f"{LOGIN_URL}?v=3&api_key={self._key}"

    def exchange_token(self, request_token: str) -> dict[str, str]:
        """`POST /session/token`; returns only access_token and user_id."""
        data = self._json(
            self._request(
                "POST", "/session/token", auth=False,
                data={"api_key": self._key, "request_token": request_token,
                      "checksum": checksum(self._key, request_token, self._secret)},
            )
        )  # fmt: skip
        if not isinstance(data, dict) or "access_token" not in data:
            raise ProviderError(ErrorCode.BAD_DATA, "session response lacks an access token")
        self._token = str(data["access_token"])
        return {"access_token": self._token, "user_id": str(data.get("user_id", ""))}

    # ---- reads --------------------------------------------------------------------------------
    def profile(self) -> dict[str, Any]:
        data = self._json(self._request("GET", "/user/profile"))
        return {k: v for k, v in dict(data).items() if "token" not in k}

    def instruments(self, exchange: str | None = None) -> str:
        """The daily CSV dump as text (gunzipped when needed)."""
        res = self._request("GET", f"/instruments/{exchange}" if exchange else "/instruments")
        raw = res.content
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8")

    def historical(
        self, token: int, interval: str, start: datetime, end: datetime, *, oi: bool = False,
        continuous: bool = False,
    ) -> list[list[Any]]:  # fmt: skip
        fmt = "%Y-%m-%d %H:%M:%S"
        params = {
            "from": start.astimezone(IST).strftime(fmt),
            "to": end.astimezone(IST).strftime(fmt),
        }
        if oi:
            params["oi"] = "1"
        if continuous:
            params["continuous"] = "1"
        data = self._json(
            self._request("GET", f"/instruments/historical/{token}/{interval}", params=params)
        )
        candles = data.get("candles") if isinstance(data, dict) else None
        if not isinstance(candles, list):
            raise ProviderError(ErrorCode.BAD_DATA, "historical response lacks candles")
        return candles

    def ltp(self, keys: list[str]) -> dict[str, Any]:
        data = self._json(self._request("GET", "/quote/ltp", params=[("i", k) for k in keys]))
        return dict(data)
