"""Chart routes: instruments, columnar bars with cursor paging, prefs, drawings."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.conftest import ORIGIN
from tests.helpers import ORACLE

pytestmark = pytest.mark.db
SYM = "NIFTY 50"
H = {"Origin": ORIGIN}


@pytest.fixture
def loaded(api: tuple[TestClient, Engine]) -> TestClient:
    c, _ = api
    r = c.post(f"/api/v1/datasets/import?symbol={SYM}&tick_size=0.05", content=ORACLE.read_bytes(),
               headers={**H, "Content-Type": "text/csv"})  # fmt: skip
    assert r.status_code == 200
    return c


def test_instruments_and_bars_columnar(loaded: TestClient) -> None:
    ins = loaded.get("/api/v1/instruments").json()
    assert [i["tradingsymbol"] for i in ins] == [SYM] and ins[0]["tick_size"] == 0.05
    b = loaded.get("/api/v1/bars", params={"symbol": SYM, "tf": "1m", "limit": 100}).json()
    assert len(b["t"]) == 100 and b["volume_kind"] == "absent"
    assert all(len(b[k]) == 100 for k in "ohlcv") and b["t"] == sorted(b["t"])
    assert b["next_cursor"] == b["t"][0]
    assert loaded.get("/api/v1/bars", params={"symbol": "NOPE"}).status_code == 404
    assert loaded.get("/api/v1/bars", params={"symbol": SYM, "tf": "7m"}).status_code == 422


def test_cursor_paging_has_no_gaps_or_duplicates(loaded: TestClient) -> None:
    seen: list[int] = []
    cur = None
    while True:
        p = {"symbol": SYM, "tf": "5m", "limit": 400} | ({"cursor": cur} if cur else {})
        page = loaded.get("/api/v1/bars", params=p).json()
        assert not seen or page["t"][-1] < seen[0]  # strictly older than what we have
        seen = page["t"] + seen
        cur = page["next_cursor"]
        if cur is None:
            break
    assert (
        seen == sorted(set(seen)) and len(seen) == 1200
    )  # 1199 final + the partial last bucket, once each


def test_higher_timeframes_resample(loaded: TestClient) -> None:
    for tf, n in (("15m", 400), ("1h", 100), ("1d", 17)):
        b = loaded.get("/api/v1/bars", params={"symbol": SYM, "tf": tf, "limit": 5000}).json()
        assert len(b["t"]) >= n - 1, tf
    d = loaded.get("/api/v1/bars", params={"symbol": SYM, "tf": "1d"}).json()
    assert len(d["t"]) == 17 and d["next_cursor"] is None


def test_resample_cost_is_reported(loaded: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    out = []
    for tf in ("1m", "5m", "1h", "1d"):
        t0 = time.perf_counter()
        loaded.get("/api/v1/bars", params={"symbol": SYM, "tf": tf, "limit": 5000})
        out.append(f"{tf} {1000 * (time.perf_counter() - t0):.0f}ms")
    with capsys.disabled():
        print("\nbars limit=5000 on the oracle:", ", ".join(out))


def test_prefs_roundtrip(loaded: TestClient) -> None:
    assert (
        loaded.put(
            "/api/v1/prefs/chart", json={"value": {"symbol": SYM, "tf": "5m"}}, headers=H
        ).status_code
        == 200
    )
    loaded.put("/api/v1/prefs/chart", json={"value": {"symbol": SYM, "tf": "15m"}}, headers=H)
    assert loaded.get("/api/v1/prefs").json()["chart"] == {"symbol": SYM, "tf": "15m"}


def test_drawings_crud_and_origin(loaded: TestClient) -> None:
    body = {"symbol": SYM, "kind": "trendline",
            "data": {"points": [{"t": 1_700_000_000, "p": 100.5}, {"t": 1_700_000_600, "p": 101}], "color": "#fff"}}  # fmt: skip
    assert (
        loaded.post(
            "/api/v1/drawings", json=body, headers={"Origin": "http://evil.example"}
        ).status_code
        == 403
    )
    d = loaded.post("/api/v1/drawings", json=body, headers=H).json()
    assert d["id"].startswith("drw_") and d["kind"] == "trendline"
    got = loaded.get("/api/v1/drawings", params={"symbol": SYM}).json()
    assert got == [d]
    moved = {"points": [{"t": 1_700_000_100, "p": 90.0}, {"t": 1_700_000_700, "p": 91}]}
    assert loaded.put(f"/api/v1/drawings/{d['id']}", json=moved, headers=H).status_code == 200
    assert (
        loaded.get("/api/v1/drawings", params={"symbol": SYM}).json()[0]["data"]["points"][0]["p"]
        == 90.0
    )
    assert (
        loaded.post(
            "/api/v1/drawings", json={**body, "data": {"points": []}}, headers=H
        ).status_code
        == 422
    )
    assert loaded.delete(f"/api/v1/drawings/{d['id']}", headers=H).status_code == 200
    assert loaded.delete(f"/api/v1/drawings/{d['id']}", headers=H).status_code == 404
    assert loaded.get("/api/v1/drawings", params={"symbol": SYM}).json() == []


def test_chart_routes_need_login(client: TestClient) -> None:
    for p in ("/instruments", "/bars?symbol=X", "/prefs", "/drawings?symbol=X"):
        assert client.get("/api/v1" + p).status_code == 401
