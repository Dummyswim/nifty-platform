from datetime import date

import pytest
from sqlalchemy import Connection, text

from nifty.cli import run_engine
from nifty.contracts import Instrument
from nifty.db.bars import read_bars, upsert_bars
from nifty.db.instruments import upsert_instrument
from nifty.db.runs import find_run, load_events, load_overlays, load_plots, persist_run
from nifty.engines.runner import run_batch
from tests.helpers import CAL, wave
from tests.sma_cross_engine import registered

pytestmark = pytest.mark.db
IID = "csv:T"
P = '{"fast": 2, "slow": 3}'


@pytest.fixture
def seeded(db_conn: Connection) -> Connection:
    upsert_instrument(
        db_conn, Instrument(instrument_id=IID, provider="csv", tradingsymbol="T", tick_size=0.05)
    )
    upsert_bars(db_conn, wave(date(2026, 11, 2)) + wave(date(2026, 11, 3)))
    return db_conn


def n(c: Connection, table: str) -> int:
    return int(c.execute(text(f"select count(*) from {table}")).scalar() or 0)


def run(c: Connection, **kw: object) -> list[str]:
    with registered():
        return run_engine(c, engine_id="test.sma_cross", symbol="T", params=P, **kw)  # type: ignore[arg-type]


def test_persist_roundtrip_matches_the_in_memory_result(seeded: Connection) -> None:
    bars = read_bars(seeded, IID, "1m")
    with registered():
        r = run_batch("test.sma_cross", {"fast": 2, "slow": 3}, bars, "5m", source_id="snap_t")
        run_id, created = persist_run(seeded, r)
    assert created and run_id.startswith("run_") and find_run(seeded, r) == run_id
    assert load_plots(seeded, run_id) == r.plots  # NaN was stored as null and comes back as None
    assert load_events(seeded, run_id) == r.events
    assert load_overlays(seeded, run_id) == r.overlays
    assert r.events and r.overlays
    assert n(seeded, "plot_points") == len(r.plots)
    assert seeded.execute(
        text("select panel->'rows'->0->>'value' from engine_runs")
    ).scalar() == str(len(r.bars))


def test_same_key_returns_existing_run_and_writes_nothing(seeded: Connection) -> None:
    first = run(seeded)
    assert "created" in first[-1] and len(first) <= 15
    counts = {
        t: n(seeded, t)
        for t in ("engine_runs", "plot_points", "events", "overlay_elements", "datasets")
    }
    second = run(seeded)
    assert "existing, nothing written" in second[-1]
    assert {t: n(seeded, t) for t in counts} == counts
    assert first[-1].split()[1] == second[-1].split()[1]  # same run_id


def test_timeframe_and_params_are_part_of_the_key_but_ui_is_not(seeded: Connection) -> None:
    run(seeded)
    run(seeded, timeframe="15m")
    assert n(seeded, "engine_runs") == 2  # config_hash does not cover the timeframe
    with registered():
        run_engine(seeded, engine_id="test.sma_cross", symbol="T", params='{"fast": 3, "slow": 5}')
        ui = run_engine(
            seeded, engine_id="test.sma_cross", symbol="T",
            params='{"fast": 2, "slow": 3, "ui": {"color": "#ff0000"}}',
        )  # fmt: skip
    assert n(seeded, "engine_runs") == 3 and "existing" in ui[-1]
    assert n(seeded, "engine_configs") == 2


def test_no_persist_writes_nothing(seeded: Connection) -> None:
    lines = run(seeded, persist=False)
    assert "not persisted" in lines[-1]
    assert (
        n(seeded, "engine_runs") == 0
        and n(seeded, "datasets") == 0
        and n(seeded, "plot_points") == 0
    )


def test_date_range_and_summary_shape(seeded: Connection) -> None:
    lines = run(seeded, from_date="2026-11-02", to_date="2026-11-02", persist=False)
    assert "1m bars 375" in lines[1] and "chart bars 75" in lines[1] and len(lines) <= 15
    both = run(seeded, persist=False)
    assert "1m bars 750" in both[1]


def test_unready_engine_is_refused_unless_allowed(seeded: Connection) -> None:
    with registered(ready=False):
        refused = run_engine(seeded, engine_id="test.sma_cross", symbol="T", params=P)
        assert refused[0].startswith("refused") and n(seeded, "engine_runs") == 0
        ok = run_engine(
            seeded, engine_id="test.sma_cross", symbol="T", params=P, allow_unready=True
        )
        assert "created" in ok[-1]


def test_unknown_engine_symbol_and_empty_range(seeded: Connection) -> None:
    assert run_engine(seeded, engine_id="nope", symbol="T")[0].startswith("unknown engine")
    with registered():
        assert run_engine(seeded, engine_id="test.sma_cross", symbol="ZZZ")[0].startswith(
            "unknown symbol"
        )
        empty = run_engine(
            seeded,
            engine_id="test.sma_cross",
            symbol="T",
            from_date="2026-01-05",
            to_date="2026-01-06",
        )
        assert empty == ["no 1m bars in range"]


def test_params_from_file_and_availability_filter(seeded: Connection, tmp_path) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "p.json"
    f.write_text(P)
    with registered():
        lines = run_engine(seeded, engine_id="test.sma_cross", symbol="T", params=f"@{f}")
    run_id = lines[-1].split()[1]
    events = load_events(seeded, run_id)
    mid = events[len(events) // 2].available_at_utc
    early = load_events(seeded, run_id, available_by=mid)
    assert 0 < len(early) < len(events) and all(e.available_at_utc <= mid for e in early)
    assert len(load_overlays(seeded, run_id, available_by=mid)) <= len(
        load_overlays(seeded, run_id)
    )
    assert CAL is not None


def test_run_engine_and_snapshot_cli_share_one_snapshot_id(seeded: Connection) -> None:
    """D07/C04 key everything on snapshot_id: both CLI paths must derive the same one."""
    from nifty.cli import session_range
    from nifty.db.bars import create_snapshot

    lo, hi = session_range(CAL, "2026-11-02", "2026-11-03")
    assert lo is not None and hi is not None
    want = create_snapshot(seeded, IID, "1m", lo, hi).snapshot_id
    explicit = run(seeded, from_date="2026-11-02", to_date="2026-11-03")
    implicit = run(seeded)  # no range: session bounds of the first and last stored bar
    assert f"source {want}" in explicit[1] and f"source {want}" in implicit[1]
    assert "existing" in implicit[-1]  # one run, not two
    assert n(seeded, "engine_runs") == 1 and n(seeded, "datasets") == 1
