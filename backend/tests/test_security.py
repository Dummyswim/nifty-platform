"""C15 security checks: every route needs the session cookie, the WS closes without it, no wildcard CORS."""

import re

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import ORIGIN

OPEN = {("GET", "/healthz"), ("GET", "/readyz")}  # liveness/readiness only
# the browser's Kite redirect carries no app cookie; it only exchanges a request_token we verify
KITE_REDIRECT = re.compile(r"/kite/callback")


def operations(client: TestClient) -> list[tuple[str, str]]:
    spec = client.app.openapi()  # type: ignore[attr-defined]
    return [
        (m.upper(), p)
        for p, item in spec["paths"].items()
        for m in item
        if m in ("get", "post", "put", "patch", "delete")
    ]


def test_every_route_but_health_needs_the_cookie(client: TestClient) -> None:
    ops = operations(client)
    assert len(ops) >= 40
    leaks = []
    for method, path in ops:
        if (method, path) in OPEN or KITE_REDIRECT.search(path):
            continue
        url = re.sub(r"\{[^}]+\}", "x", path)
        r = client.request(
            method, url, headers={"Origin": ORIGIN}, json={} if method != "GET" else None
        )
        if r.status_code != 401 and not (
            path.endswith("/auth/login") or path.endswith("/auth/logout")
        ):
            leaks.append((method, path, r.status_code))
    assert leaks == []


def test_health_is_the_only_open_data_route(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/engines").status_code == 401
    assert client.get("/api/v1/research/runs").status_code == 401


def test_websocket_closes_without_the_cookie(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/v1/stream") as ws:
        ws.receive_text()


def test_no_wildcard_cors(client: TestClient) -> None:
    for origin in ("http://evil.example", ORIGIN):
        r = client.get("/healthz", headers={"Origin": origin})
        assert r.headers.get("access-control-allow-origin") != "*"
    pre = client.options(
        "/api/v1/engines",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert pre.headers.get("access-control-allow-origin") not in ("*", "http://evil.example")


def test_no_unauthenticated_schema_pages(client: TestClient) -> None:
    for p in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(p).status_code == 404


def test_compose_ports_are_loopback_only() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.yml").read_text()
    ports = re.findall(r"ports:\s*\[([^\]]*)\]", text)
    assert ports, "no published ports found"
    for entry in ports:
        for p in re.findall(r'"([^"]+)"', entry):
            assert p.startswith("127.0.0.1:"), p
