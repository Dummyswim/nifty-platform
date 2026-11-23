from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import random
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, time, timedelta
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import AsyncMock, patch

from vwap_scalper import (
    IST, RSI, Bar, Config, Engine, LiveOutput, apply_overrides, main, read_csv, resample, run_live, summarize, write_csv,
)

DAY = datetime(2026, 11, 2, 9, 15, tzinfo=IST)  # a Monday
STEP = timedelta(minutes=5)


def v_closes(down_bars=30, down=0.8, up_bars=4, up=5.0, zig=2.0):
    """Slow zig-zag decline followed by a sharp rally: the engine's first BUY lands on the last bar."""
    closes, price = [], 25000.0
    for i in range(down_bars + up_bars):
        price += up if i >= down_bars else -down
        closes.append(price + zig * (1 if i % 2 else -1))
    return closes


def make_bars(closes, day=DAY, mirror=False):
    bars, prev = [], closes[0]
    for i, close in enumerate(closes):
        o, h, l, c = prev, max(prev, close) + 1.5, min(prev, close) - 1.5, close
        if mirror:
            o, h, l, c = 50000 - o, 50000 - l, 50000 - h, 50000 - c
        bars.append(Bar(day + STEP * i, o, h, l, c))
        prev = close
    return bars


def feed(engine, bars):
    events = []
    for bar in bars:
        events += engine.on_bar(bar)
    return events


def signalled(mirror=False, cfg=None):
    engine = Engine(cfg or Config())
    events = feed(engine, make_bars(v_closes(), mirror=mirror))
    return engine, [e for e in events if e["type"] == "SIGNAL"]


def next_bar(engine, o, h, l, c):
    return Bar(engine.bars[-1].ts + STEP, o, h, l, c)


class IndicatorTests(unittest.TestCase):
    def test_rsi_extremes_and_wilder_reference(self):
        up, down, flat = RSI(14), RSI(14), RSI(14)
        for i in range(30):
            ru, rd, rf = up.update(100 + i), down.update(200 - i), flat.update(100)
        self.assertEqual((ru, rd, rf), (100.0, 0.0, 50.0))
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
        ref = RSI(14)
        values = [ref.update(c) for c in closes]
        self.assertTrue(all(v is None for v in values[:-2]))
        # StockCharts' published 70.53 / 66.32 use rounded intermediates; unrounded Wilder gives 70.46 / 66.25
        self.assertAlmostEqual(values[-2], 70.53, delta=0.1)
        self.assertAlmostEqual(values[-1], 66.32, delta=0.1)

    def test_vwap_is_volume_weighted_and_twap_without_volume(self):
        weighted = Engine()
        weighted.on_bar(Bar(DAY, 100, 100, 100, 100, 1), trade=False)
        weighted.on_bar(Bar(DAY + STEP, 110, 110, 110, 110, 3), trade=False)
        self.assertEqual(weighted.rows[-1]["vwap_kind"], "VWAP")
        self.assertAlmostEqual(weighted.rows[-1]["vwap"], 107.5)
        equal = Engine()
        equal.on_bar(Bar(DAY, 100, 100, 100, 100), trade=False)
        equal.on_bar(Bar(DAY + STEP, 110, 110, 110, 110), trade=False)
        self.assertEqual(equal.rows[-1]["vwap_kind"], "TWAP")
        self.assertAlmostEqual(equal.rows[-1]["vwap"], 105.0)

    def test_vwap_resets_each_session(self):
        engine = Engine()
        engine.on_bar(Bar(DAY, 100, 100, 100, 100, 5), trade=False)
        engine.on_bar(Bar(DAY + timedelta(days=1), 200, 200, 200, 200, 5), trade=False)
        self.assertAlmostEqual(engine.rows[-1]["vwap"], 200.0)

    def test_resample_is_session_aligned_and_drops_out_of_session_bars(self):
        minute = timedelta(minutes=1)
        raw = [Bar(DAY - minute, 1, 1, 1, 1)]
        raw += [Bar(DAY + minute * i, 100 + i, 101 + i, 99 + i, 100.5 + i, 10) for i in range(10)]
        raw += [Bar(DAY.replace(hour=15, minute=30), 5, 5, 5, 5)]
        out = resample(raw, 5)
        self.assertEqual([b.ts.strftime("%H:%M") for b in out], ["09:15", "09:20"])
        self.assertEqual((out[0].o, out[0].h, out[0].l, out[0].c, out[0].v), (100, 105, 99, 104.5, 50))


class SignalTests(unittest.TestCase):
    def test_buy_signal_fills_at_next_open_and_hits_target(self):
        engine, signals = signalled()
        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertEqual(sig["side"], "BUY")
        self.assertLess(sig["stop"], sig["ref"])
        self.assertGreater(sig["target"], sig["ref"])
        self.assertIsNone(engine.pos)
        events = engine.on_bar(next_bar(engine, sig["ref"], sig["target"] + 1, sig["ref"] - 1, sig["target"]))
        self.assertEqual([e["type"] for e in events], ["ENTRY", "EXIT"])
        trade = engine.trades[0]
        self.assertEqual((trade["entry"], trade["exit"], trade["reason"]), (sig["ref"], sig["target"], "TP"))
        self.assertAlmostEqual(trade["net_pts"], trade["gross_pts"] - trade["cost_pts"])
        self.assertAlmostEqual(trade["gross_r"], Config().target_r)
        self.assertLess(trade["r"], trade["gross_r"])

    def test_sell_signal_is_the_mirror_image(self):
        engine, signals = signalled(mirror=True)
        self.assertEqual([s["side"] for s in signals], ["SELL"])
        sig = signals[0]
        self.assertGreater(sig["stop"], sig["ref"])
        self.assertLess(sig["target"], sig["ref"])
        events = engine.on_bar(next_bar(engine, sig["ref"], sig["ref"] + 1, sig["target"] - 1, sig["target"]))
        self.assertEqual([e["type"] for e in events], ["ENTRY", "EXIT"])
        self.assertEqual((engine.trades[0]["reason"], engine.trades[0]["exit"]), ("TP", sig["target"]))
        self.assertGreater(engine.trades[0]["net_pts"], 0)

    def test_same_bar_stop_and_target_resolves_to_stop(self):
        engine, (sig,) = signalled()
        engine.on_bar(next_bar(engine, sig["ref"], sig["target"] + 1, sig["stop"] - 1, sig["ref"]))
        trade = engine.trades[0]
        self.assertEqual((trade["reason"], trade["exit"]), ("SL", sig["stop"]))
        self.assertLess(trade["r"], -1.0)

    def test_next_open_gapping_through_stop_skips_the_trade(self):
        engine, (sig,) = signalled()
        events = engine.on_bar(next_bar(engine, sig["stop"] - 1, sig["stop"], sig["stop"] - 3, sig["stop"] - 2))
        self.assertEqual([e["type"] for e in events], ["SKIP"])
        self.assertEqual(engine.trades, [])

    def test_open_beyond_stop_while_in_trade_fills_at_the_open(self):
        engine, (sig,) = signalled()
        engine.on_bar(next_bar(engine, sig["ref"], sig["ref"] + 2, sig["ref"] - 1, sig["ref"] + 1))
        self.assertIsNotNone(engine.pos)
        gap = sig["stop"] - 5
        engine.on_bar(next_bar(engine, gap, gap + 1, gap - 1, gap))
        self.assertEqual(engine.trades[0]["exit"], gap)

    def test_end_of_day_flattens_at_the_bar_close(self):
        engine, (sig,) = signalled(cfg=replace(Config(), flat_time=time(12, 15)))
        engine.on_bar(next_bar(engine, sig["ref"], sig["ref"] + 2, sig["ref"] - 1, sig["ref"] + 1))
        self.assertIsNotNone(engine.pos)
        events = engine.on_bar(next_bar(engine, sig["ref"] + 1, sig["ref"] + 2, sig["ref"], sig["ref"] + 1.5))
        self.assertEqual(events[-1]["reason"], "EOD")
        self.assertEqual(engine.trades[0]["exit"], sig["ref"] + 1.5)
        self.assertIsNone(engine.pos)

    def test_warmup_bars_never_signal(self):
        engine = Engine()
        self.assertEqual(sum((engine.on_bar(b, trade=False) for b in make_bars(v_closes())), []), [])
        self.assertEqual(engine.signals, [])
        self.assertEqual(len(engine.rows), 34)

    def test_cost_gate_blocks_targets_that_cannot_pay_for_themselves(self):
        _, signals = signalled(cfg=replace(Config(), cost_bps=60))
        self.assertEqual(signals, [])

    def test_trade_and_loss_limits(self):
        _, signals = signalled(cfg=replace(Config(), max_trades_day=0))
        self.assertEqual(signals, [])
        engine = Engine()
        bars = make_bars(v_closes())
        feed(engine, bars[:-1])
        engine.r_today = -3.0
        self.assertEqual(engine.on_bar(bars[-1]), [])

    def test_entry_window_is_enforced(self):
        late = replace(Config(), entry_end=time(11, 0))
        self.assertEqual(signalled(cfg=late)[1], [])

    def test_causality_prefix_events_equal_full_run_events(self):
        rng = random.Random(7)
        bars = []
        for d in range(4):
            closes = v_closes(up=5.0 + d) + [25000 + rng.uniform(-30, 30) for _ in range(30)]
            bars += make_bars(closes, day=DAY + timedelta(days=d), mirror=bool(d % 2))
        full = Engine()
        per_bar = [full.on_bar(b) for b in bars]
        self.assertTrue(any(e["type"] == "SIGNAL" for evs in per_bar for e in evs))
        for cut in (40, 100, 170, 230):
            part = Engine()
            self.assertEqual([part.on_bar(b) for b in bars[:cut]], per_bar[:cut])

    def test_duplicate_or_old_bars_are_ignored(self):
        engine = Engine()
        bars = make_bars(v_closes())
        feed(engine, bars)
        before = len(engine.rows)
        self.assertEqual(engine.on_bar(bars[10]), [])
        self.assertEqual(engine.on_bar(bars[-1]), [])
        self.assertEqual(len(engine.rows), before)


class CliAndLiveTests(unittest.TestCase):
    def test_overrides_parse_by_field_type(self):
        cfg = apply_overrides(Config(), ["target_r=2", "rsi_cross_bars=5", "entry_end=14:00"])
        self.assertEqual((cfg.target_r, cfg.rsi_cross_bars, cfg.entry_end), (2.0, 5, time(14, 0)))
        with self.assertRaises(SystemExit):
            apply_overrides(Config(), ["nonsense=1"])

    def test_summary_counts_costs_and_drawdown(self):
        trades = [dict(net_pts=n, gross_pts=n + 6, cost_pts=6, r=n / 10, gross_r=(n + 6) / 10) for n in (20, -10, -10, 30)]
        s = summarize(trades)
        self.assertEqual((s["trades"], s["win_rate"], s["net_pts"], s["max_drawdown_pts"], s["max_losing_streak"]), (4, 0.5, 30, 20, 2))
        self.assertAlmostEqual(s["profit_factor"], 50 / 20)

    def test_backtest_cli_from_one_minute_csv(self):
        engine, (sig,) = signalled()
        five = engine.bars + [next_bar(engine, sig["ref"], sig["target"] + 1, sig["ref"] - 1, sig["target"])]
        one = []
        for b in five:  # five 1-minute bars that resample back to exactly this 5-minute bar
            m = timedelta(minutes=1)
            one += [Bar(b.ts, b.o, b.o, b.o, b.o), Bar(b.ts + m, b.o, b.h, b.o, b.h), Bar(b.ts + 2 * m, b.h, b.h, b.l, b.l),
                    Bar(b.ts + 3 * m, b.l, b.l, b.l, b.l), Bar(b.ts + 4 * m, b.l, b.c, b.l, b.c)]
        with tempfile.TemporaryDirectory() as directory:
            src, trades = Path(directory) / "nifty_1m.csv", Path(directory) / "trades.csv"
            write_csv(one, src)
            self.assertEqual(len(read_csv(src)), len(one))
            out = io.StringIO()
            with redirect_stdout(out):
                main(["backtest", "--csv", str(src), "--trades", str(trades), "--no-chart"])
            self.assertIn("Trades 1", out.getvalue())
            self.assertIn("TWAP", out.getvalue())
            with trades.open() as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([(r["side"], r["reason"]) for r in rows], [("BUY", "TP")])

    def test_live_output_prints_label_and_logs_jsonl(self):
        engine = Engine()
        bars = make_bars(v_closes())
        feed(engine, bars[:-1])
        events = engine.on_bar(bars[-1])
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "live.jsonl"
            out, screen = LiveOutput(log, None, False), io.StringIO()
            with redirect_stdout(screen):
                out.handle(engine, bars[-1], events)
            out.fh.close()
            self.assertIn(" BUY ", screen.getvalue())
            self.assertIn("SL ", screen.getvalue())
            self.assertEqual([json.loads(line)["type"] for line in log.read_text().splitlines()], ["SIGNAL"])

    @unittest.skipUnless(find_spec("plotly"), "plotly not installed")
    def test_chart_contains_buy_and_sell_labels(self):
        from scalper_chart import build_chart

        for mirror, label in ((False, "BUY"), (True, "SELL")):
            engine, _ = signalled(mirror=mirror)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "chart.html"
                build_chart(engine, path)
                html = path.read_text()
            self.assertIn(f"\\u003cb\\u003e{label}\\u003c", html)
            self.assertNotIn("\\u003cb\\u003e" + ("SELL" if label == "BUY" else "BUY") + "\\u003c", html)


class LiveFeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticks_become_bars_and_disconnect_is_raised(self):
        from nifty_assistant import FeedDisconnect

        def quote(price, at):
            return struct.pack("<BhBifi", 2, 16, 0, 13, price, int(at.timestamp()))

        class Socket:
            def __init__(self):
                ticks = []
                for bucket in range(5):
                    start = DAY + STEP * bucket
                    ticks += [quote(25000 + 10 * bucket, start + timedelta(seconds=5)),
                              quote(25005 + 10 * bucket, start + timedelta(seconds=200))]
                self.messages = iter(ticks + [struct.pack("<BhBih", 50, 10, 0, 13, 807)])
                self.sent = []

            async def send(self, payload):
                self.sent.append(json.loads(payload))

            async def recv(self):
                return next(self.messages)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return DAY.astimezone(tz)

        class Recorder:
            def __init__(self):
                self.seen = []

            def handle(self, engine, bar, events):
                self.seen.append((bar.ts, bar.o, bar.c))

        socket, connection = Socket(), AsyncMock()
        connection.__aenter__.return_value = socket
        args = argparse.Namespace(segment="IDX_I", security_id="13", no_seed=True, stale_seconds=60, max_reconnects=1)
        engine, recorder = Engine(), Recorder()
        env = {"DHAN_ACCESS_TOKEN": "t", "DHAN_CLIENT_ID": "c"}
        with patch.dict(os.environ, env), patch("websockets.connect", return_value=connection), patch("vwap_scalper.datetime", Clock):
            with self.assertRaisesRegex(FeedDisconnect, "807"):
                await run_live(engine, recorder, args)
        self.assertEqual(socket.sent[0]["RequestCode"], 17)
        self.assertEqual(socket.sent[0]["InstrumentList"], [{"ExchangeSegment": "IDX_I", "SecurityId": "13"}])
        # the first partial candle is discarded; the last one is still open
        self.assertEqual([(ts.strftime("%H:%M"), o, c) for ts, o, c in recorder.seen],
                         [("09:20", 25010, 25015), ("09:25", 25020, 25025), ("09:30", 25030, 25035)])
        self.assertEqual(len(engine.bars), 3)


if __name__ == "__main__":
    unittest.main()
