"""Live pipeline on nifty_test: ticks -> bars -> engines -> DB, restart equivalence (D14), the
WebSocket (cookie auth, snapshot-first, Redis-down polling), reconcile and status."""

import json
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from starlette.websockets import WebSocketDisconnect

import nifty.engines.nvs  # noqa: F401
from nifty.api.stream import Outbox
from nifty.collector.demo import DEMO_ID, ORACLE, ticks_of
from nifty.collector.reconcile import plan_reconcile
from nifty.collector.service import Pipeline, Publisher
from nifty.contracts import Bar, Instrument
from nifty.db.bars import read_bars
from nifty.db.instruments import upsert_instrument
from nifty.db.live import read_status, status_summary
from nifty.engines.runner import run_batch
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from tests.conftest import ORIGIN, TABLES
from tests.helpers import CAL

pytestmark = pytest.mark.db
INS = Instrument(instrument_id=DEMO_ID, provider="csv", tradingsymbol=DEMO_ID, tick_size=0.05)


@pytest.fixture(scope="module")
def src() -> list[Bar]:
    ok, _ = validate_bars(parse_csv(ORACLE, instrument_id=DEMO_ID), CAL)
    return [
        b
        for b in ok
        if date(2026, 10, 26) <= CAL.session_date(b.bar_start_utc) <= date(2026, 10, 27)
    ]


@pytest.fixture
def db(migrated_url: str) -> Iterator[Engine]:
    eng = create_engine(migrated_url)
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        upsert_instrument(c, INS)
    yield eng
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    eng.dispose()


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def pipe(db: Engine, clock: Clock | None = None) -> Pipeline:
    p = Pipeline(db, None, CAL, clock or Clock(), provider="csv")
    p.add_feed(INS, {"pine.nvs_scalper": {}})
    return p


def feed(p: Pipeline, bars: list[Bar]) -> None:
    for b in bars:
        for t in ticks_of(b):
            p.handle_tick(DEMO_ID, t)


def stored(db: Engine, tf: str = "5m") -> dict[str, object]:
    with db.connect() as c:
        rid = c.execute(
            text("select run_id from engine_runs where timeframe = :tf"), {"tf": tf}
        ).scalar_one()
        return {
            "plots": [(r[0], r[1]) for r in c.execute(text("select bar_start_utc, values from plot_points where run_id=:r order by 1"), {"r": rid})],
            "events": [r[0] for r in c.execute(text("select envelope from events where run_id=:r order by ord"), {"r": rid})],
            "n_overlays": c.execute(text("select count(*) from overlay_elements where run_id=:r"), {"r": rid}).scalar_one(),
        }  # fmt: skip


def test_ticks_become_bars_and_engine_outputs_equal_batch(db: Engine, src: list[Bar]) -> None:
    p = pipe(db)
    feed(p, src)
    p.finish()
    with db.connect() as c:
        bars = read_bars(c, DEMO_ID, "1m")
    assert [(b.bar_start_utc, b.open, b.high, b.low, b.close) for b in bars] == [
        (b.bar_start_utc, b.open, b.high, b.low, b.close) for b in src
    ]
    assert all(b.volume_kind == "absent" and b.provider == "csv" for b in bars)
    batch = run_batch(
        "pine.nvs_scalper",
        {},
        bars,
        "5m",
        instrument=INS,
        calendar=CAL,
        source_id=f"live:{DEMO_ID}",
    )
    s = stored(db)
    assert [t for t, _ in s["plots"]] == [t for t, _ in batch.plots]  # type: ignore[attr-defined]
    assert [e["event_id"] for e in s["events"]] == [str(e.event_id) for e in batch.events]  # type: ignore[attr-defined]
    assert len(s["events"]) >= 6 and s["n_overlays"] == len(batch.overlays)  # type: ignore[arg-type]
    assert p.status()["ticks"] == 4 * len(src)


@pytest.mark.parametrize("cut", [300, 560])
def test_kill_and_restart_midday_equals_uninterrupted(db: Engine, src: list[Bar], cut: int) -> None:
    a = pipe(db)
    feed(
        a, src[:cut]
    )  # process A is killed here: no finish(), ticks of the open minute are lost with it
    b = pipe(db)  # restart: replays the stored 1m bars, then continues with the rest
    feed(b, src[cut - 1 :])  # the re-sent minute is a duplicate: upsert is a no-op
    b.finish()
    got = stored(db)
    with db.connect() as c:
        bars = read_bars(c, DEMO_ID, "1m")
    batch = run_batch(
        "pine.nvs_scalper",
        {},
        bars,
        "5m",
        instrument=INS,
        calendar=CAL,
        source_id=f"live:{DEMO_ID}",
    )
    assert [e["event_id"] for e in got["events"]] == [str(e.event_id) for e in batch.events]  # type: ignore[attr-defined]
    assert [t for t, _ in got["plots"]] == [t for t, _ in batch.plots]  # type: ignore[attr-defined]
    assert len(bars) == len(src)  # no duplicate bars


def test_stale_watchdog_and_status_table(db: Engine, src: list[Bar]) -> None:
    clk = Clock()
    p = pipe(db, clk)
    p.state["connected"] = True
    feed(p, src[:3])
    assert p.status()["stale"] is False
    clk.t = 20.0  # silence for 20 s (injected clock)
    assert p.status()["stale"] is True and p.status()["last_tick_age_s"] == 20.0
    p.write_status()
    with db.connect() as c:
        row = read_status(c)
    assert row is not None and status_summary(row)["state"] == "stale"
    assert status_summary((row[0], 60.0))["state"] == "down"
    assert status_summary(({"connected": False}, 1.0))["state"] == "disconnected"
    assert (
        status_summary(({"connected": True, "auth_expired": True}, 1.0))["state"] == "auth_expired"
    )
    assert status_summary(None)["state"] == "down"
    clk.t = 21.0
    feed(p, src[3:5])  # ticks resume: recovers
    assert p.status()["stale"] is False or p.status()["last_tick_age_s"] == 0.0


def test_reconcile_plan() -> None:
    base = datetime(2026, 11, 23, 4, 0).astimezone()

    def mk(i: int, c: float) -> Bar:
        return Bar(
            instrument_id="k", provider="kite", timeframe="1m",
            bar_start_utc=base + timedelta(minutes=i), bar_end_utc=base + timedelta(minutes=i + 1),
            open=1, high=3, low=0.5, close=c, volume=0, volume_kind="absent", received_at_utc=base,
        )  # fmt: skip

    stored_ = [mk(0, 2), mk(1, 2)]
    plan = plan_reconcile(stored_, [mk(0, 2), mk(1, 2.5), mk(2, 2)])
    assert [b.close for b in plan] == [2.5, 2] and all(
        "reconciled" in b.quality_flags for b in plan
    )
    assert plan_reconcile(stored_, stored_) == []


def test_outbox_drops_provisional_first_then_flags_slow_client() -> None:
    o = Outbox()
    for i in range(200):
        o.put({"i": i})
    o.put({"p": 1}, droppable=True)
    assert o.dropped == 1 and not o.overflow
    o.put({"essential": 1})
    assert o.overflow


# ---- WebSocket ----------------------------------------------------------------------------------
@pytest.fixture
def ws_client(api: tuple[TestClient, Engine], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(
        "REDIS_URL", "redis://127.0.0.1:1/0"
    )  # unreachable: forces the polling fallback
    return api[0]


def test_ws_requires_cookie(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect("/ws/v1/stream"):
        pass
    assert e.value.code == 1008


def test_ws_snapshot_first_then_updates_by_polling_and_no_duplicates_on_resubscribe(
    ws_client: TestClient, db: Engine, src: list[Bar]
) -> None:
    p = pipe(db)
    feed(p, src[:400])
    sub = {
        "op": "subscribe",
        "instrument": DEMO_ID,
        "timeframe": "5m",
        "engines": ["pine.nvs_scalper"],
    }
    with ws_client.websocket_connect("/ws/v1/stream", headers={"Origin": ORIGIN}) as ws:
        ws.send_text(json.dumps(sub))
        first = ws.receive_json()
        assert (
            first["type"] == "snapshot" and first["bars"]["t"] and first["instrument_id"] == DEMO_ID
        )
        assert first["bars"]["t"] == sorted(set(first["bars"]["t"]))
        cursor = first["cursor"]
        seen = {m["type"] for m in (ws.receive_json() for _ in range(2))}
        assert seen <= {"status", "panel", "event", "bar"} and "status" in seen
        feed(
            p, src[400:430]
        )  # new bars arrive after the subscription: found by polling (Redis is down)
        got = []
        for _ in range(12):
            m = ws.receive_json()
            got.append(m)
            if m["type"] == "bar" and max(m["bars"]["t"]) > cursor:
                break
        assert any(m["type"] == "bar" and max(m["bars"]["t"]) > cursor for m in got)
    with ws_client.websocket_connect("/ws/v1/stream", headers={"Origin": ORIGIN}) as ws:
        ws.send_text(json.dumps({**sub, "cursor": cursor}))
        snap = ws.receive_json()
        assert (
            snap["bars"]["t"] and min(snap["bars"]["t"]) >= cursor
        )  # only bars at/after the cursor
        assert len(snap["bars"]["t"]) == len(set(snap["bars"]["t"]))


def test_ws_rejects_bad_subscribe_and_foreign_origin(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/v1/stream") as ws:
        ws.send_text(json.dumps({"op": "subscribe", "instrument": "NOPE", "timeframe": "1m"}))
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 1003
    with (
        pytest.raises(WebSocketDisconnect) as e2,
        ws_client.websocket_connect("/ws/v1/stream", headers={"Origin": "http://evil.example"}),
    ):
        pass
    assert e2.value.code == 1008


def test_collector_status_endpoint_and_instrument_list_hides_empty_demo(
    ws_client: TestClient, db: Engine, src: list[Bar]
) -> None:
    assert ws_client.get("/api/v1/collector/status").json()["state"] == "down"
    assert [
        i["tradingsymbol"] for i in ws_client.get("/api/v1/instruments").json()
    ] == []  # demo has no bars yet
    p = pipe(db)
    p.state["connected"] = True
    feed(p, src[:5])
    p.finish()
    p.write_status()
    st = ws_client.get("/api/v1/collector/status").json()
    assert st["state"] == "live" and st["instruments"] == [DEMO_ID] and st["ticks"] == 20
    assert [i["tradingsymbol"] for i in ws_client.get("/api/v1/instruments").json()] == [DEMO_ID]


@pytest.mark.parametrize("tf", ["1m", "15m", "1h"])
def test_pine_engines_run_live_on_every_intraday_timeframe(
    db: Engine, src: list[Bar], tf: str
) -> None:
    p = pipe(db)
    feed(p, src)
    p.finish()
    with db.connect() as c:
        assert (
            c.execute(text("select count(distinct timeframe) from engine_runs")).scalar_one() == 7
        )
        bars = read_bars(c, DEMO_ID, "1m")
    batch = run_batch(
        "pine.nvs_scalper", {}, bars, tf, instrument=INS, calendar=CAL, source_id=f"live:{DEMO_ID}"
    )
    got = stored(db, tf)
    assert [t for t, _ in got["plots"]] == [t for t, _ in batch.plots]  # type: ignore[attr-defined]
    assert [e["event_id"] for e in got["events"]] == [str(e.event_id) for e in batch.events]  # type: ignore[attr-defined]


def test_restart_with_a_sliding_warmup_window_rewrites_overlays(
    db: Engine, src: list[Bar], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restart replays only the last WARMUP_SESSIONS, so zone ids restart from z1: the stored
    outputs must be those of the replay, not a mix with the earlier window's rows."""
    import nifty.collector.service as svc
    import nifty.engines.balu  # noqa: F401

    monkeypatch.setattr(svc, "WARMUP_SESSIONS", 1)
    day2 = [b for b in src if CAL.session_date(b.bar_start_utc) == date(2026, 10, 27)]
    cut = len(src) - len(day2) + 60

    def balu(db: Engine) -> Pipeline:
        p = Pipeline(db, None, CAL, Clock(), provider="csv")
        p.add_feed(INS, {"pine.balu_zone": {}})
        return p

    feed(balu(db), src[:cut])
    b = balu(db)  # restart: replays day 2 only
    feed(b, src[cut - 1 :])
    b.finish()
    batch = run_batch(
        "pine.balu_zone", {}, day2, "1m", instrument=INS, calendar=CAL, source_id=f"live:{DEMO_ID}"
    )
    with db.connect() as c:
        rid = c.execute(text("select run_id from engine_runs where timeframe = '1m'")).scalar_one()
        got = c.execute(
            text("select id, ver, deleted, element->>'p0' from overlay_elements where run_id=:r order by ord"),
            {"r": rid},
        ).all()  # fmt: skip
    want = [(o.id, o.ver, o.deleted, None if o.p0 is None else str(o.p0)) for o in batch.overlays]
    assert len(want) > 0
    assert [tuple(r) for r in got] == want


def test_provisional_bars_are_throttled_per_instrument_not_globally(
    db: Engine, src: list[Bar]
) -> None:
    """An option ticking right after the index must still get its forming bar published."""
    other = INS.model_copy(update={"instrument_id": "DEMO:OPT", "tradingsymbol": "DEMO:OPT"})
    with db.begin() as c:
        upsert_instrument(c, other)
    sent: list[tuple[str, str]] = []

    class Rec(Publisher):
        def publish(self, channel: str, msg: dict[str, object]) -> None:
            sent.append((channel, str(msg["type"])))

    p = Pipeline(db, Rec(None), CAL, Clock(), provider="csv")
    p.add_feed(INS)
    p.add_feed(other)
    t = next(ticks_of(src[0]))
    p.handle_tick(DEMO_ID, t)
    p.handle_tick("DEMO:OPT", t)
    assert (f"live:{DEMO_ID}", "provisional") in sent
    assert ("live:DEMO:OPT", "provisional") in sent
