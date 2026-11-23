import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from nifty.config import get_settings

pytestmark = pytest.mark.db


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


def test_select_one(test_db_url: str) -> None:
    with create_engine(test_db_url).connect() as c:
        assert c.execute(text("select 1")).scalar() == 1
