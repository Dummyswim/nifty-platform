"""KiteClient / KiteProvider / master / tokens, offline (httpx.MockTransport + handcrafted fixtures)."""

import gzip
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from nifty.marketdata.base import ErrorCode, ProviderError
from nifty.marketdata.kite.client import (
    ForbiddenEndpoint,
    KiteClient,
    RateLimiter,
    checksum,
    map_error,
)  # fmt: skip
from nifty.marketdata.kite.master import (
    expiries,
    front_month_future,
    nifty_index,
    option_universe,
    parse_master,
    strike_step,
)  # fmt: skip
from nifty.marketdata.kite.provider import KiteProvider, windows
from nifty.marketdata.kite.tokens import (
    TokenDecryptError,
    decrypt_token,
    encrypt_token,
    next_expiry,
)  # fmt: skip
from nifty.timeutil import IST

FX = Path(__file__).resolve().parents[4] / "fixtures" / "kite_recorded"
SECRET, TOKEN, RTOK = "SECRET-VALUE-XYZ", "ACCESS-TOKEN-VALUE-123", "REQ-TOKEN-ABC"


def fx(name: str) -> str:
    return (FX / name).read_text()


def client(handler, **kw) -> KiteClient:  # type: ignore[no-untyped-def]
    slept: list[float] = []
    c = KiteClient("kkey", SECRET, TOKEN, transport=httpx.MockTransport(handler), sleep=slept.append,
                   limiter=RateLimiter(clock=lambda: 0.0, sleep=lambda s: None), **kw)  # fmt: skip
    c.slept = slept  # type: ignore[attr-defined]
    return c


def test_checksum_known_answer() -> None:
    # sha256("kkey" + "rtok" + "sseccc"), computed independently of the code under test
    assert (
        checksum("kkey", "rtok", "sseccc")
        == "925c2d745253e723e58f9993e812e81fcaa53b5e4ee23ac54a899ca3638afdb3"
    )


def test_exchange_token_form_headers_and_no_auth_header() -> None:
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, text=fx("session_token.json"))

    c = client(h)
    out = c.exchange_token(RTOK)
    r = seen[0]
    assert (r.method, r.url.path) == ("POST", "/session/token")
    form = dict(x.split("=") for x in r.content.decode().split("&"))
    assert form["api_key"] == "kkey" and form["request_token"] == RTOK
    assert form["checksum"] == checksum("kkey", RTOK, SECRET) and len(form["checksum"]) == 64
    assert "authorization" not in r.headers and r.headers["X-Kite-Version"] == "3"
    assert out == {"access_token": "ACCESS-TOKEN-VALUE-123", "user_id": "AB1234"}


def test_authenticated_headers_and_profile_has_no_tokens() -> None:
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, text=fx("profile.json"))

    p = client(h).profile()
    assert (
        seen[0].headers["Authorization"] == f"token kkey:{TOKEN}"
        and seen[0].headers["X-Kite-Version"] == "3"
    )
    assert p["user_id"] == "AB1234" and not any("token" in k for k in p)


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (
            403,
            {"status": "error", "error_type": "TokenException", "message": "x"},
            ErrorCode.AUTH_EXPIRED,
        ),
        (
            429,
            {"status": "error", "error_type": "NetworkException", "message": "slow down"},
            ErrorCode.RATE_LIMITED,
        ),
        (
            400,
            {"status": "error", "error_type": "InputException", "message": "bad"},
            ErrorCode.BAD_DATA,
        ),
        (
            400,
            {"status": "error", "error_type": "PermissionException", "message": "no"},
            ErrorCode.ENTITLEMENT,
        ),
        (
            400,
            {
                "status": "error",
                "error_type": "GeneralException",
                "message": "Subscription required",
            },
            ErrorCode.ENTITLEMENT,
        ),
        (
            503,
            {"status": "error", "error_type": "GeneralException", "message": "down"},
            ErrorCode.NETWORK,
        ),
        (502, {}, ErrorCode.NETWORK),
        (404, {}, ErrorCode.BAD_DATA),
    ],
)
def test_error_mapping(status: int, body: dict[str, str], code: ErrorCode) -> None:
    assert map_error(status, body).code == code


def test_retries_only_network_and_rate_limited_with_backoff() -> None:
    calls = {"n": 0}

    def h(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429 if calls["n"] < 3 else 200, text=fx("profile.json"))

    c = client(h)
    assert c.profile()["user_id"] == "AB1234" and calls["n"] == 3
    assert len(c.slept) == 2 and c.slept[1] > c.slept[0]  # type: ignore[attr-defined]

    calls["n"] = 0
    always = client(lambda r: httpx.Response(429, json={"status": "error", "message": "m"}))
    with pytest.raises(ProviderError) as e:
        always.profile()
    assert e.value.code == ErrorCode.RATE_LIMITED and len(always.slept) == 3  # type: ignore[attr-defined]

    n = {"c": 0}

    def tok(req: httpx.Request) -> httpx.Response:
        n["c"] += 1
        return httpx.Response(403, text=fx("error_token.json"))

    with pytest.raises(ProviderError) as e2:
        client(tok).profile()
    assert e2.value.code == ErrorCode.AUTH_EXPIRED and n["c"] == 1  # never retried

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ProviderError) as e3:
        client(boom).profile()
    assert e3.value.code == ErrorCode.NETWORK


def test_allowlist_blocks_everything_else_before_any_io() -> None:
    def never(req: httpx.Request) -> httpx.Response:
        raise AssertionError("I/O happened")

    c = client(never)
    for method, path in [
        ("POST", "/orders/regular"), ("DELETE", "/session/token"), ("GET", "/portfolio/holdings"),
        ("PUT", "/gtt/triggers/1"), ("GET", "/instruments/historical/1/week"), ("POST", "/quote"),
        ("GET", "/user/margins"),
    ]:  # fmt: skip
        with pytest.raises(ForbiddenEndpoint):
            c._request(method, path)  # noqa: SLF001
    ok = [("GET", "/instruments/NFO"), ("GET", "/instruments"), ("GET", "/quote/ohlc")]
    from nifty.marketdata.kite.client import ALLOWLIST

    assert all(any(m == mm and p.match(pp) for m, p in ALLOWLIST) for mm, pp in ok)


def test_rate_limiter_with_fake_clock() -> None:
    t = {"now": 0.0}
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(round(s, 4))
        t["now"] += s

    lim = RateLimiter(clock=lambda: t["now"], sleep=sleep)
    for _ in range(4):
        lim.acquire("historical")  # 3 req/s -> 1/3 s apart
    assert slept == [0.3333, 0.3333, 0.3333]
    slept.clear()
    lim.acquire("quote")
    lim.acquire("quote")  # 1 req/s
    assert slept == [1.0]
    slept.clear()
    lim.acquire("other")
    lim.acquire("other")  # 10 req/s
    assert slept == [0.1]


def test_redaction_in_errors_reprs_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    leak = f"bad token {TOKEN} secret {SECRET} access_token={TOKEN}&checksum=abc"
    c = client(
        lambda r: httpx.Response(
            400, json={"status": "error", "error_type": "InputException", "message": leak}
        )
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as e:
        c.profile()
    blob = str(e.value) + repr(e.value) + repr(c) + caplog.text
    for secret in (TOKEN, SECRET):
        assert secret not in blob
    assert "checksum=abc" not in blob

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach with Authorization: token kkey:{TOKEN}")

    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as e2:
        client(boom).profile()
    assert TOKEN not in str(e2.value) + caplog.text


def test_instruments_dump_gzip_and_plain() -> None:
    raw = fx("instruments.csv")
    assert (
        client(lambda r: httpx.Response(200, content=gzip.compress(raw.encode()))).instruments()
        == raw
    )
    assert client(lambda r: httpx.Response(200, content=raw.encode())).instruments() == raw


# ---- provider ---------------------------------------------------------------------------------
def test_windows_split_by_day_limit() -> None:
    a = datetime(2026, 1, 1, tzinfo=UTC)
    w = windows(a, a + timedelta(days=150), 60)
    assert [(y - x).days for x, y in w] == [60, 60, 30] and w[1][0] == w[0][1]
    assert windows(a, a, 60) == []


def test_provider_chunks_merges_dedupes_and_converts() -> None:
    ins = next(i for i in parse_master(fx("instruments.csv")) if i.instrument_type == "INDEX")
    reqs: list[dict[str, str]] = []
    first = json.loads(fx("historical_nifty_1m.json"))["data"]["candles"]

    def h(req: httpx.Request) -> httpx.Response:
        reqs.append(dict(req.url.params))
        assert req.url.path == f"/instruments/historical/{ins.provider_token}/minute"
        return httpx.Response(
            200, json={"status": "success", "data": {"candles": first}}
        )  # same candles every window

    p = KiteProvider(client(h), [ins], day_limit=60)
    start = datetime(2026, 9, 1, tzinfo=IST)
    bars = list(
        p.historical(
            ins,
            "1m",
            datetime(2026, 11, 16, 9, 0, tzinfo=IST),
            datetime(2026, 11, 16, 9, 30, tzinfo=IST),
        )
    )
    assert (
        len(reqs) == 1
        and reqs[0]["from"] == "2026-11-16 09:00:00"
        and reqs[0]["to"] == "2026-11-16 09:30:00"
    )
    assert [b.bar_start_utc for b in bars][0] == datetime(
        2026, 11, 16, 3, 45, tzinfo=UTC
    )  # 09:15 +05:30
    assert all(b.provider == "kite" and b.volume_kind == "absent" and b.volume == 0.0 for b in bars)
    assert len(bars) == 3 and bars[0].open == 25100.5
    reqs.clear()
    long = list(p.historical(ins, "1m", start, start + timedelta(days=130)))
    assert len(reqs) == 3  # 60 + 60 + 10 days; identical candles dedupe
    assert len(long) == 0 or len({b.bar_start_utc for b in long}) == len(long)
    with pytest.raises(ProviderError) as e:
        list(p.historical(ins, "5m", start, start + timedelta(days=1)))
    assert e.value.code == ErrorCode.BAD_DATA
    assert p.status()["provider"] == "kite"


# ---- master -----------------------------------------------------------------------------------
def test_master_parse_filters_and_helpers() -> None:
    ins = parse_master(fx("instruments.csv"), "v1")
    ids = {i.tradingsymbol for i in ins}
    assert "RELIANCE" not in ids and "BANKNIFTY26NOVFUT" not in ids  # other underlyings stay out
    assert len(ins) == 10 and all(i.metadata_version == "v1" for i in ins)
    idx = nifty_index(ins)
    assert (
        idx
        and idx.provider_token == 256265
        and idx.instrument_type == "INDEX"
        and idx.instrument_id == "kite:NSE:NIFTY 50"
    )
    fut = next(i for i in ins if i.tradingsymbol == "NIFTY26NOVFUT")
    assert (fut.lot_size, fut.tick_size, fut.expiry, fut.strike) == (
        75,
        0.1,
        date(2026, 11, 24),
        None,
    )
    assert front_month_future(ins, date(2026, 11, 23)).tradingsymbol == "NIFTY26NOVFUT"  # type: ignore[union-attr]
    assert front_month_future(ins, date(2026, 11, 24)).tradingsymbol == "NIFTY26NOVFUT"  # type: ignore[union-attr]
    assert front_month_future(ins, date(2026, 11, 25)).tradingsymbol == "NIFTY26DECFUT"  # type: ignore[union-attr]
    assert front_month_future(ins, date(2027, 2, 1)) is None
    assert expiries(ins, "CE") == [date(2026, 11, 24), date(2026, 12, 29)]
    u = option_universe(ins, date(2026, 11, 24), "CE")
    assert [o.strike for o in u] == [24900.0, 24950.0, 25000.0]
    assert strike_step(ins, date(2026, 11, 24)) == 50.0  # derived, never hardcoded
    with pytest.raises(ProviderError):
        parse_master("a,b\n1,2\n")


# ---- tokens -----------------------------------------------------------------------------------
def test_token_encryption_roundtrip_and_wrong_key() -> None:
    blob = encrypt_token("app-secret", TOKEN)
    assert TOKEN.encode() not in blob and decrypt_token("app-secret", blob) == TOKEN
    with pytest.raises(TokenDecryptError):
        decrypt_token("other-secret", blob)
    with pytest.raises(TokenDecryptError):
        encrypt_token("", "x")


def test_next_expiry_is_0600_ist() -> None:
    def ist(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
        return datetime(y, m, d, hh, mm, tzinfo=IST).astimezone(UTC)

    assert next_expiry(ist(2026, 11, 23, 9, 0)) == ist(2026, 11, 24, 6, 0)
    assert next_expiry(ist(2026, 11, 23, 5, 59)) == ist(2026, 11, 23, 6, 0)
    assert next_expiry(ist(2026, 11, 23, 6, 0)) == ist(2026, 11, 24, 6, 0)


def test_index_without_listed_tick_size_is_none_not_zero() -> None:
    # the master lists 0 for indexes; 0 must never reach the engines as a tick size (division by zero)
    idx = next(i for i in parse_master(fx("instruments.csv")) if i.instrument_type == "INDEX")
    assert idx.tick_size is None
