import pytest
from sqlalchemy import Connection, text

pytestmark = pytest.mark.db


def test_migrations_and_hypertable(db_conn: Connection) -> None:
    assert db_conn.execute(text("select version_num from alembic_version")).scalar() == "0002"
    assert (
        db_conn.execute(
            text(
                "select count(*) from timescaledb_information.hypertables where hypertable_name='bars'"
            )
        ).scalar()
        == 1
    )
