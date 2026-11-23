# Nifty VWAP-spread scalper

Advisory scalper for Nifty. It prints and charts **BUY / SELL / EXIT** labels and never places an order.
One causal bar-by-bar engine (`vwap_scalper.py`) drives both the backtest and the live Dhan feed, so what you
backtest is what you see live. Chart code is in `scalper_chart.py`.

It builds on the "Intraday Trading with RSI & VWAP" rules (long: RSI > 60 and close above VWAP; short: RSI < 40
and close below VWAP; stop at the entry candle's low/high), and adds the *spread* idea and a trend filter.

## Rules (5-minute bars by default)

**Spread** = `close - session VWAP`, expressed in ATR units.

- *How far*: `dev_atr = (close - VWAP) / ATR(14)`
- *How fast*: `speed = dev_atr - dev_atr[3 bars ago]` (how much the spread widened in the last 3 bars)

**BUY** on a completed bar when all of these hold (**SELL** is the exact mirror):

| Gate | Long |
|---|---|
| Trend | close > VWAP and EMA9 > EMA21 |
| Momentum | RSI >= 60 and it was below 60 within the last 3 bars (a fresh cross, not a stale one) |
| Spread distance | `0.25 <= dev_atr <= 1.6` (far enough to be a move, not so far that you chase) |
| Spread speed | `speed >= +0.35 ATR` |
| Candle | green, closing in its top 40% |
| No chop | at most 3 VWAP side flips in the last 20 bars |
| Session | bar ends 09:30-14:45 IST, 30 bars of warm-up, at most 6 trades and -3R per day, 2-bar cooldown |
| Costs | target must be at least 2.5x the round-trip cost |

**Trade management** (fill at the *next* bar's open):

- Stop = signal candle low (high for shorts), at least 0.7 ATR away; signal skipped if it would be more than 1.8 ATR.
- Target = 1.5R. After +1R the stop moves to entry plus round-trip cost (breakeven that actually breaks even).
- Exit signals, acted on at the next open: close back through VWAP (`VWAP_LOSS`), stretched beyond 2 ATR and stalling
  (`STRETCH_STALL`), RSI back through 50 (`RSI_FADE`), 15 bars (`TIME`). Flat by 15:15 (`EOD`).
- If a stop and a target fall inside one bar, the stop is assumed to hit first.

Every threshold is a field of `Config`; override with `--set name=value` (e.g. `--set target_r=2 --set max_dev_atr=2.2`).

## Run it

Use the project's virtual environment (`/Users/bchavdi/jnpr-tasks/practicalenv/venv/bin/python`):

```bash
cd selfhosted
PY=/Users/bchavdi/jnpr-tasks/practicalenv/venv/bin/python
$PY -m pip install -r requirements-scalper.txt

# 1. data: ~25 days of 1-minute candles. Yahoo is a quick unofficial source for the index.
$PY vwap_scalper.py fetch --source yahoo --days 25 --out data/nifty_1m.csv

#    Better: Dhan history of the Nifty FUTURE, which has volume and therefore a true VWAP.
export DHAN_ACCESS_TOKEN=... DHAN_CLIENT_ID=...
$PY vwap_scalper.py find-future                       # prints the current-month security id
$PY vwap_scalper.py fetch --source dhan --segment NSE_FNO --security-id <ID> --days 60 --out data/nifty_fut_1m.csv

# 2. backtest: report in the terminal, trades CSV, and an HTML chart with BUY/SELL labels
$PY vwap_scalper.py backtest --csv data/nifty_fut_1m.csv --minutes 5 --last-days 5
#    -> logs/scalper_trades.csv, logs/scalper_chart.html (open in a browser)

# 3. live advisory on the future (needs the Dhan token; run during market hours)
$PY vwap_scalper.py live --segment NSE_FNO --security-id <ID> --notify
#    -> coloured BUY/SELL badge + bell in the terminal, logs/scalper_live.jsonl, logs/scalper_live.html (auto-refresh)
```

Live mode seeds about 6 days of Dhan history so EMA/RSI/ATR are warm, and backfills the first partial candle and any
reconnect gaps from Dhan REST. History never produces alerts. You place the real entry, stop and target with your broker;
paper positions inside the program are not persisted across restarts.

## Read this before trusting any number

- **Index has no volume.** On `IDX_I` (and Yahoo's `^NSEI`) there is no volume, so the engine uses an equal-weight session
  average (TWAP) and prints `VWAP kind: TWAP`. Use the Nifty future for a real VWAP; the TWAP version is only a
  stand-in and will not match your charting platform's VWAP.
- **Costs are an assumption.** `cost_bps = 2.5` per round trip (about 6 points at 25,000) stands in for brokerage, STT,
  exchange fees and slippage. Replace it with your own numbers; scalps are very sensitive to this.
- **Sample result (not a claim):** on 17 sessions of 1-minute Yahoo index data (Oct 22 - Nov 16 2026), untuned, the engine
  took 12-16 trades (under one a day), gross expectancy was about +0.2R (5m, 3m) to +0.4R (1m) and roughly zero after costs.
  That sample is far too small to say anything about the edge. Expect few signals; the gates are deliberately tight.
- **Frequency vs quality knobs:** `rsi_cross_bars`, `max_dev_atr`, `min_speed_atr`, `--minutes`. Loosening them raises
  trade count and (usually) costs per R. Tune on one period and test on another, never on the same one.
- **Forward test first.** Run `live` on paper for at least 4-6 weeks and compare it against the backtest of the same days
  (entry price, fills, trade count) before risking money. This is not investment advice and past results do not predict
  future ones.

## TradingView version

`Nifty_VWAP_Spread_Scalper.pine` (Pine v6 strategy) mirrors this engine with RSI enabled: same default gates, BUY/SELL labels with
price, SL and TP (hover for the reason), the VWAP and EMAs, shaded spread zones, a dashboard, and `alert()` messages.

1. TradingView > Pine Editor > paste the file > Add to chart, on a **5-minute** Nifty chart.
2. Symbol: `NSE:NIFTY1!` (future) gives a true VWAP; `NSE:NIFTY` has no volume, so the line becomes the TWAP.
3. Properties tab: commission is preset to 0.0125 % per side (= `cost_bps` 2.5 round trip). If you change the cost input,
   set commission to `bps / 200`. Order size is 1, so the Strategy Tester reads in index points.
4. Live: create an alert on the strategy with "Any alert() function call" to get BUY / SELL / EXIT messages.

**Optional RSI:** open Settings > Inputs > Trend & momentum > **Use RSI (entries and exits)**.
It is **on by default**, preserving the original RSI thresholds, fresh-cross requirement and `RSI_FADE` exit.
Turning it off bypasses those checks, including waiting for RSI to warm up; EMA, VWAP distance/speed, candle quality,
chop filtering, stops, targets, breakeven, other exits, warm-up bars and session/daily limits remain active.
The dashboard shows `RSI (ON)` or `RSI (OFF)`, and entry alert messages and label tooltips say `RSI OFF` when disabled.
This switch applies to the TradingView version; the Python engine retains its original RSI rules.

**Switching during a live session:** TradingView recalculates the entire loaded history when an input changes,
including simulated positions and daily limits. This is not a switch that applies only to future candles.
Existing alerts keep their saved script/settings snapshot: **recreate alerts after changing the toggle or updating
the script**. Keep a separate record of live signals and the mode used; recalculated historical labels are not a
record of which mode you actually used earlier in the session.

Checked by running the Pine logic in an open-source Pine runtime (PineTS) on `data/nifty_1m.csv` resampled to 5m: the same
15 entries (time and price) as `logs/scalper_trades.csv`, and 14 of 15 exits on the same bar for the same reason. It has
not been compiled by TradingView itself, so report any compile message. Known differences:

- SL and TP are the prices printed on the label (anchored to the signal-bar close). Python re-anchors them to the actual
  next-open fill and skips a trade if that open gaps too far; Pine takes the fill as is.
- If one bar touches both stop and target, TradingView decides the intrabar path; Python assumes the stop first. The bar
  magnifier (paid plans) gives a truer answer.
- EMA is SMA-seeded in Pine; the difference vanishes after about 100 bars. Chart history is limited by your plan, so the
  Strategy Tester covers far fewer bars than a CSV.

## Tests

```bash
$PY -m pytest test_vwap_scalper.py -q
```

Covers VWAP/TWAP, Wilder RSI, resampling, BUY and SELL signals, next-open fills, stop-first on same-bar hits,
gaps, EOD flat, cost gate, daily limits, causality (a run on a prefix gives the same events as the full run), the
backtest CLI, the chart labels and a mocked Dhan tick feed.
