import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nifty.api.main import create_app
from nifty.security import hash_password

ORIGIN = "http://127.0.0.1:8080"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_PASSWORD_HASH", hash_password("correct horse"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    monkeypatch.setenv("APP_ORIGINS", f"{ORIGIN},http://127.0.0.1:5173")
    os.environ.pop("DATABASE_URL", None)
    with TestClient(create_app()) as c:
        yield c
