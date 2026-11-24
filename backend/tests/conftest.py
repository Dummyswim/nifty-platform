import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from nifty.api.main import create_app
from nifty.config import get_settings
from nifty.db.session import get_engine
from nifty.security import hash_password

ORIGIN = "http://127.0.0.1:8080"
TABLES = "prefs, collector_status, ticks, kite_tokens, instrument_masters, drawings, trades, backtests, jobs, events, overlay_elements, plot_points, engine_runs, engine_configs, bars, datasets, instruments"
ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_PASSWORD_HASH", hash_password("correct horse"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    monkeypatch.setenv("APP_ORIGINS", f"{ORIGIN},http://127.0.0.1:5173")
    os.environ.pop("DATABASE_URL", None)
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Creates `nifty_test` on the configured server; never touches the dev DB.

    Skips only when the server is unreachable; an auth failure must fail loudly.
    """
    base = make_url(get_settings().database_url)
    eng = create_engine(
        base.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 2},
    )
    try:
        with eng.connect() as c:
            if not c.execute(text("select 1 from pg_database where datname='nifty_test'")).scalar():
                c.execute(text("create database nifty_test"))
    except OperationalError as e:
        if "authentication failed" in str(e).lower():
            raise
        pytest.skip("postgres unreachable")
    return base.set(database="nifty_test").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def migrated_url(test_db_url: str) -> str:
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    eng = create_engine(test_db_url)
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    eng.dispose()
    return test_db_url


@pytest.fixture
def db_conn(migrated_url: str) -> Iterator[Connection]:
    """A connection in a transaction that is rolled back after each test."""
    eng = create_engine(migrated_url)
    with eng.connect() as conn:
        trans = conn.begin()
        yield conn
        trans.rollback()
    eng.dispose()


@pytest.fixture
def sma_engine() -> Iterator[None]:
    from tests.sma_cross_engine import registered

    with registered():
        yield


@pytest.fixture
def api(
    migrated_url: str, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Engine]]:
    monkeypatch.setenv("DATABASE_URL", migrated_url)
    get_engine.cache_clear()
    eng = create_engine(migrated_url)
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    assert (
        client.post(
            "/api/v1/auth/login", json={"password": "correct horse"}, headers={"Origin": ORIGIN}
        ).status_code
        == 200
    )
    yield client, eng
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    eng.dispose()
    get_engine.cache_clear()
