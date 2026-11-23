"""The TradingView-golden path has no real export yet: feed it files written from our own run in
the exported layouts and expect an exact match (Tier A error 0, B/C complete)."""

import csv
from datetime import timedelta
from pathlib import Path

import pytest

from nifty.contracts import Instrument
from nifty.engines.runner import run_batch
from nifty.marketdata.importer import parse_csv
from nifty.marketdata.validation import validate_bars
from nifty.parity.cli import SERIES, run_parity
from nifty.parity.compare import exit_bar_start
from nifty.parity.tv_io import load_tv_trades
from nifty.timeutil import to_ist
from tests.helpers import CAL, ORACLE

INST = Instrument(
    instrument_id="csv:NIFTY 50", provider="csv", tradingsymbol="NIFTY 50", tick_size=0.05
)


def test_golden_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ok, _ = validate_bars(parse_csv(ORACLE, instrument_id=INST.instrument_id), CAL)
    r = run_batch("pine.nvs_scalper", {}, ok, "5m", instrument=INST, calendar=CAL)
    titles = {v: k for k, v in SERIES["pine.nvs_scalper"].items()}
    with (tmp_path / "ohlc_plots.csv").open("w", newline="") as f:  # no volume column at all
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", *titles.values()])
        for b, (_, pl) in zip(r.bars, r.plots, strict=True):
            w.writerow([int(b.bar_start_utc.timestamp()), b.open, b.high, b.low, b.close,
                        *[("" if pl[n] is None else pl[n]) for n in titles]])  # fmt: skip
    with (tmp_path / "trades.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Trade #", "Type", "Signal", "Date/Time", "Price INR"])
        for i, t in enumerate(r.trades, 1):
            s = t.side
            ex = to_ist(exit_bar_start(t, timedelta(minutes=5))).strftime("%Y-%m-%d %H:%M")
            w.writerow([i, f"Exit {s}", t.exit_reason, ex, t.exit_px])
            w.writerow([i, f"Entry {s}", "BUY" if s == "long" else "SELL",
                        to_ist(t.entry_time).strftime("%Y-%m-%d %H:%M"), t.entry_px])  # fmt: skip
    assert len(load_tv_trades(tmp_path / "trades.csv")) == 15
    lines, rc = run_parity("pine.nvs_scalper", golden=tmp_path)
    out = "\n".join(lines)
    assert rc == 0 and "Tier A OK" in out and "entries 15/15 | exits 15/15" in out, out
