"""D14 for the live runner: feeding 1m bars one by one, including a kill + replay restart mid-day,
yields exactly the batch outputs."""

from datetime import date

import pytest

import nifty.engines.nvs  # noqa: F401  (registers the engine)
from nifty.contracts import Instrument
from nifty.engines.live import LiveRun
from nifty.engines.runner import run_batch
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from tests.helpers import CAL, ORACLE

INST = Instrument(
    instrument_id="csv:NIFTY 50", provider="csv", tradingsymbol="NIFTY 50", tick_size=0.05
)


@pytest.fixture(scope="module")
def bars():  # type: ignore[no-untyped-def]
    ok, _ = validate_bars(parse_csv(ORACLE, instrument_id=INST.instrument_id), CAL)
    return [
        b
        for b in ok
        if date(2026, 10, 27) <= CAL.session_date(b.bar_start_utc) <= date(2026, 11, 2)
    ]


def collect(runs: list[LiveRun], seq):  # type: ignore[no-untyped-def]
    plots, events, overlays, trades = {}, {}, {}, []
    for r, chunk in zip(runs, seq, strict=True):
        for b in chunk:
            d = r.feed(b)
            plots.update(dict(d.plots))
            events.update({o: e for o, e in d.events})  # idempotent by ord, like the DB
            overlays.update({o: e for o, e in d.overlays})
            trades += d.trades
    return plots, events, overlays, trades


def mk() -> LiveRun:
    return LiveRun("pine.nvs_scalper", {}, INST, "5m", CAL, source_id="snap")


def test_live_equals_batch(bars) -> None:  # type: ignore[no-untyped-def]
    batch = run_batch(
        "pine.nvs_scalper", {}, bars, "5m", instrument=INST, calendar=CAL, source_id="snap"
    )
    plots, events, overlays, trades = collect([mk()], [bars])
    assert list(plots.items()) == batch.plots
    assert [events[k] for k in sorted(events)] == batch.events
    assert [overlays[k] for k in sorted(overlays)] == batch.overlays
    assert trades == batch.trades and len(trades) >= 4


@pytest.mark.parametrize("cut", [500, 1200, 1555])  # before, inside and after trades
def test_kill_and_restart_midday_is_identical(bars, cut: int) -> None:  # type: ignore[no-untyped-def]
    batch = run_batch(
        "pine.nvs_scalper", {}, bars, "5m", instrument=INST, calendar=CAL, source_id="snap"
    )
    # process A dies after `cut` bars; process B restarts by replaying every stored bar from the
    # start (what the collector does) and goes on live. Writes are idempotent by key, as in the DB.
    plots, events, overlays, _ = collect([mk()], [bars[:cut]])
    b = mk()
    for bar in bars:
        d = b.feed(bar)
        plots.update(dict(d.plots))
        events.update({o: e for o, e in d.events})
        overlays.update({o: e for o, e in d.overlays})
    assert list(plots.items()) == batch.plots
    assert [events[k] for k in sorted(events)] == batch.events
    assert [overlays[k] for k in sorted(overlays)] == batch.overlays


def test_provisional_never_changes_state(bars) -> None:  # type: ignore[no-untyped-def]
    batch = run_batch(
        "pine.nvs_scalper", {}, bars, "5m", instrument=INST, calendar=CAL, source_id="snap"
    )
    r = mk()
    seen = 0
    for b in bars:
        d = r.feed(b)
        seen += len(d.events)
        forming = b.model_copy(
            update={
                "bar_start_utc": b.bar_end_utc,
                "bar_end_utc": b.bar_end_utc + (b.bar_end_utc - b.bar_start_utc),
                "finalized": False,
            }
        )
        r.provisional(forming)
    assert seen == len(batch.events) and r.n_events == len(batch.events)
