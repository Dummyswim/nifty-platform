"""Kite token store, status, callback and jobs against nifty_test, with a mocked Kite transport."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from nifty.config import Settings
from nifty.db import kite as dbkite
from nifty.db.jobs import get_job
from nifty.db.kite import kite_status, load_token, save_master, store_token
from nifty.marketdata.kite.client import KiteClient
from nifty.worker import process_one
from tests.conftest import ORIGIN

pytestmark = pytest.mark.db
FX = Path(__file__).resolve().parents[2] / "fixtures" / "kite_recorded"
TOKEN = "ACCESS-TOKEN-VALUE-123"


def kite_transport(calls: list[httpx.Request]) -> httpx.MockTransport:
    def h(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path == "/session/token":
            return httpx.Response(200, text=(FX / "session_token.json").read_text())
        if req.url.path == "/user/profile":
            return httpx.Response(200, text=(FX / "profile.json").read_text())
        if req.url.path == "/instruments":
            return httpx.Response(200, content=(FX / "instruments.csv").read_bytes())
        return httpx.Response(404, json={"status": "error", "message": "nope"})

    return httpx.MockTransport(h)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("KITE_API_KEY", "kkey")
    monkeypatch.setenv("KITE_API_SECRET", "ksecret")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    return Settings()


@pytest.fixture
def mocked(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    calls: list[httpx.Request] = []
    real = KiteClient

    def factory(*a: object, **kw: object) -> KiteClient:
        return real(*a, transport=kite_transport(calls), **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(dbkite, "KiteClient", factory)
    monkeypatch.setattr("nifty.api.kite_routes.KiteClient", factory)
    return calls


def test_token_store_encrypts_expires_and_never_leaks(
    db_conn: Connection, settings: Settings, mocked: list[httpx.Request]
) -> None:
    now = datetime(2026, 11, 23, 4, 0, tzinfo=UTC)  # 09:30 IST
    exp = store_token(db_conn, "test-secret", TOKEN, "AB1234", now)
    assert exp == datetime(2026, 11, 24, 0, 30, tzinfo=UTC)  # 06:00 IST the next day
    raw = db_conn.execute(text("select ciphertext from kite_tokens")).scalar_one()
    assert TOKEN.encode() not in bytes(raw)
    assert load_token(db_conn, "test-secret", now) == TOKEN
    assert load_token(db_conn, "wrong-key", now) is None  # cannot decrypt
    assert load_token(db_conn, "test-secret", exp + timedelta(seconds=1)) is None  # expired
    st = kite_status(db_conn, settings, now)
    assert st["connected"] is True and st["user_id"] == "AB1234" and st["configured"] is True
    assert TOKEN not in json.dumps(st, default=str) and "ksecret" not in json.dumps(st, default=str)
    n = len(mocked)
    kite_status(db_conn, settings, now + timedelta(minutes=2))
    assert len(mocked) == n  # validated at most every 5 minutes
    kite_status(db_conn, settings, now + timedelta(minutes=6))
    assert len(mocked) == n + 1
    after = kite_status(db_conn, settings, exp + timedelta(minutes=1))
    assert after["connected"] is False and "expired" in after["last_error"]


def test_save_master_versions_and_upserts(db_conn: Connection) -> None:
    text_ = (FX / "instruments.csv").read_text()
    v, ins = save_master(db_conn, text_)
    assert len(ins) == 10 and v.count("_") == 1
    v2, _ = save_master(db_conn, text_)
    assert (
        v2 == v
        and db_conn.execute(text("select count(*) from instrument_masters")).scalar_one() == 1
    )
    assert (
        db_conn.execute(text("select count(*) from instruments where provider='kite'")).scalar_one()
        == 10
    )
    row = db_conn.execute(text("select n_rows, n_used from instrument_masters")).first()
    assert row is not None and tuple(row) == (12, 10)
    assert len(dbkite.kite_instruments(db_conn)) == 10


def test_callback_exchanges_server_side_and_redirects(
    api: tuple[TestClient, Engine], mocked: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KITE_API_KEY", "kkey")
    monkeypatch.setenv("KITE_API_SECRET", "ksecret")
    c, eng = api
    url = c.get("/api/v1/kite/login-url").json()["url"]
    assert url == "https://kite.zerodha.com/connect/login?v=3&api_key=kkey"
    r = c.get(
        "/api/v1/kite/callback?request_token=RT123&status=success&action=login&type=login",
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == f"{ORIGIN}/settings?kite=connected"
    assert TOKEN not in r.headers["location"] + r.text
    with eng.connect() as conn:
        assert load_token(conn, "test-secret") == TOKEN
    st = c.get("/api/v1/kite/status")
    assert st.json()["connected"] is True and st.json()["user_id"] == "AB1234"
    assert TOKEN not in st.text and "ksecret" not in st.text and "RT123" not in st.text
    bad = c.get("/api/v1/kite/callback?status=failed&request_token=RT", follow_redirects=False)
    assert bad.headers["location"] == f"{ORIGIN}/settings?kite=error"
    assert (
        c.get("/api/v1/kite/callback?status=success", follow_redirects=False)
        .headers["location"]
        .endswith("kite=error")
    )


def test_kite_instruments_job_via_worker(
    api: tuple[TestClient, Engine], mocked: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KITE_API_KEY", "kkey")
    monkeypatch.setenv("KITE_API_SECRET", "ksecret")
    c, eng = api
    H = {"Origin": ORIGIN}
    j = c.post("/api/v1/kite/instruments/refresh", headers=H)
    assert j.status_code == 202
    process_one(eng)  # no token yet -> failed with a short, secret-free message
    job = c.get(f"/api/v1/jobs/{j.json()['job_id']}").json()
    assert job["status"] == "failed" and "not connected" in job["error"]
    c.get("/api/v1/kite/callback?request_token=RT&status=success", follow_redirects=False)
    j2 = c.post("/api/v1/kite/instruments/refresh", headers=H).json()
    assert j2["created"] is True  # a manual refresh is never deduped onto the failed job
    process_one(eng)
    with eng.connect() as conn:
        done = get_job(conn, j2["job_id"])
    assert done and done["status"] == "done" and "10 instruments" in done["result_ref"]
    assert c.get("/api/v1/kite/status").json()["instruments_updated_at"] is not None


def test_kite_routes_need_login(client: TestClient) -> None:
    for p in ("/login-url", "/callback?status=success&request_token=x", "/status"):
        assert client.get("/api/v1/kite" + p, follow_redirects=False).status_code == 401
    assert client.post("/api/v1/kite/instruments/refresh").status_code == 401
