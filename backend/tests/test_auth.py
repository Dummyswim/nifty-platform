from fastapi.testclient import TestClient

from nifty.api.auth import LOCKOUT_S, Throttle
from tests.conftest import ORIGIN

H = {"Origin": ORIGIN}


def login(c: TestClient, pw: str = "correct horse", **kw):  # type: ignore[no-untyped-def]
    return c.post("/api/v1/auth/login", json={"password": pw}, **kw)


def test_login_ok_sets_cookie(client: TestClient) -> None:
    r = login(client, headers=H)
    assert r.status_code == 200
    sc = r.headers["set-cookie"].lower()
    assert "nifty_session=" in sc and "httponly" in sc and "samesite=lax" in sc
    assert client.get("/api/v1/auth/me").json() == {"user_id": 1}


def test_wrong_password(client: TestClient) -> None:
    assert login(client, "nope", headers=H).status_code == 401


def test_no_cookie_401(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_bad_origin_403(client: TestClient) -> None:
    assert login(client, headers={"Origin": "http://evil.example"}).status_code == 403


def test_non_json_415(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/login", content="password=x", headers={**H, "content-type": "text/plain"}
    )
    assert r.status_code == 415


def test_password_not_set_503(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("APP_PASSWORD_HASH", "")
    assert login(client, headers=H).status_code == 503


def test_throttle_lockout_via_api(client: TestClient) -> None:
    for _ in range(5):
        assert login(client, "bad", headers=H).status_code == 401
    assert login(client, "correct horse", headers=H).status_code == 429


def test_throttle_clock() -> None:
    now = [0.0]
    t = Throttle(clock=lambda: now[0])
    for _ in range(5):
        t.fail()
    assert t.locked()
    now[0] += LOCKOUT_S + 1
    assert not t.locked()


def test_healthz_open(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_503_without_db(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x?connect_timeout=1")
    from nifty.db.session import get_engine

    get_engine.cache_clear()
    try:
        assert client.get("/readyz").status_code == 503
    finally:
        get_engine.cache_clear()
