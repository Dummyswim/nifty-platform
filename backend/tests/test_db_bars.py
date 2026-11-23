from datetime import timedelta

import pytest
from sqlalchemy import Connection, text

from nifty.contracts import Bar, Instrument
from nifty.db.bars import create_snapshot, read_bars, upsert_bars
from nifty.db.instruments import find_by_symbol, upsert_instrument
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from tests.helpers import CAL, ORACLE

pytestmark = pytest.mark.db
IID = "csv:NIFTY 50"


def load() -> list[Bar]:
    return validate_bars(parse_csv(ORACLE, instrument_id=IID), CAL)[0]


@pytest.fixture
def seeded(db_conn: Connection) -> list[Bar]:
    upsert_instrument(
        db_conn,
        Instrument(instrument_id=IID, provider="csv", tradingsymbol="NIFTY 50", tick_size=0.05),
    )
    return load()


def count(c: Connection) -> int:
    return int(c.execute(text("select count(*) from bars")).scalar() or 0)


def test_instrument_roundtrip(db_conn: Connection, seeded: list[Bar]) -> None:
    ins = find_by_symbol(db_conn, "NIFTY 50")
    assert ins is not None and ins.tick_size == 0.05 and ins.provider == "csv"


def test_upsert_is_idempotent(db_conn: Connection, seeded: list[Bar]) -> None:
    r1 = upsert_bars(db_conn, seeded)
    assert (r1.inserted, r1.revised, r1.noop) == (5996, 0, 0)
    r2 = upsert_bars(db_conn, load())  # re-parse: new received_at_utc must not matter
    assert (r2.inserted, r2.revised, r2.noop) == (0, 0, 5996)
    assert count(db_conn) == 5996


def test_differing_row_becomes_new_revision(db_conn: Connection, seeded: list[Bar]) -> None:
    upsert_bars(db_conn, seeded)
    changed = seeded[10].model_copy(update={"close": seeded[10].close + 1})
    r = upsert_bars(db_conn, [changed])
    assert (r.inserted, r.revised, r.noop) == (0, 1, 0)
    assert count(db_conn) == 5997
    latest = read_bars(db_conn, IID, "1m", seeded[10].bar_start_utc, seeded[10].bar_end_utc)
    assert len(latest) == 1 and latest[0].revision == 1 and latest[0].close == changed.close
    # replaying the changed bar is a no-op, as is the original (kept as revision 0)
    assert upsert_bars(db_conn, [changed, seeded[10]]).noop == 2


def test_read_range_and_last_n(db_conn: Connection, seeded: list[Bar]) -> None:
    upsert_bars(db_conn, seeded)
    rows = read_bars(
        db_conn, IID, "1m", seeded[0].bar_start_utc, seeded[0].bar_start_utc + timedelta(minutes=5)
    )
    assert [b.bar_start_utc for b in rows] == [b.bar_start_utc for b in seeded[:5]]
    assert rows[0] == seeded[0].model_copy(update={"received_at_utc": rows[0].received_at_utc})
    tail = read_bars(db_conn, IID, "1m", last_n=3)
    assert [b.bar_start_utc for b in tail] == [b.bar_start_utc for b in seeded[-3:]]


def test_snapshot_stable_and_sensitive_to_revisions(db_conn: Connection, seeded: list[Bar]) -> None:
    upsert_bars(db_conn, seeded)
    lo, hi = seeded[0].bar_start_utc, seeded[-1].bar_end_utc
    s1 = create_snapshot(db_conn, IID, "1m", lo, hi)
    upsert_bars(db_conn, load())  # no-op re-import
    s2 = create_snapshot(db_conn, IID, "1m", lo, hi)
    assert s1 == s2 and s1.n_rows == 5996
    assert db_conn.execute(text("select count(*) from datasets")).scalar() == 1
    upsert_bars(db_conn, [seeded[0].model_copy(update={"close": 1.0})])
    s3 = create_snapshot(db_conn, IID, "1m", lo, hi)
    assert s3.snapshot_id != s1.snapshot_id and s3.sha256 != s1.sha256


def test_snapshot_of_empty_range_raises(db_conn: Connection, seeded: list[Bar]) -> None:
    with pytest.raises(ValueError):
        create_snapshot(db_conn, IID, "1m", seeded[0].bar_start_utc, seeded[0].bar_start_utc)
