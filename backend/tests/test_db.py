import pytest
from sqlalchemy import Connection, text

from nifty.api.main import head_revision

pytestmark = pytest.mark.db


def test_migrations_and_hypertable(db_conn: Connection) -> None:
    assert (
        db_conn.execute(text("select version_num from alembic_version")).scalar() == head_revision()
    )
    assert (
        db_conn.execute(
            text(
                "select count(*) from timescaledb_information.hypertables where hypertable_name='bars'"
            )
        ).scalar()
        == 1
    )


def test_master_refresh_keeps_a_user_set_tick_size(db_conn) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from nifty.contracts import Instrument
    from nifty.db.instruments import get_instrument, upsert_instrument

    ins = Instrument(instrument_id="kite:NSE:T", provider="kite", tradingsymbol="T", tick_size=None)
    upsert_instrument(db_conn, ins)
    db_conn.execute(
        text("UPDATE instruments SET tick_size = 0.05 WHERE instrument_id = 'kite:NSE:T'")
    )
    upsert_instrument(db_conn, ins)  # a daily refresh again lists no tick size
    got = get_instrument(db_conn, "kite:NSE:T")
    assert got is not None and got.tick_size == 0.05
