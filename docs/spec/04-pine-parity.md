# pinekit & parity (modules `nifty.engines.pinekit`, `nifty.parity`)

## pinekit (D15): Pine semantics, incremental, plain floats
- `Series`: ring buffer; `s[0]` current, `s[n]` n bars back; NaN when history is insufficient. `na ≡ NaN`; `isna`, `nz(x, d=0)`; comparisons with NaN are false; `pk.max/min` propagate NaN like `math.max/min`.
- `ema(src, len)`: alpha = 2/(len+1); `ema_seed='first'` (default; first valid source value) or `'sma'`. The golden decides; log the result in STATE.
- `rma(src, len)`: alpha = 1/len, seeded with SMA(len), NaN before. `atr = rma(tr, len)`; `tr(handle_na)`: first bar = high−low. `atr_sess` = session-adjusted TR variant (NVS, research); keep the name distinct.
- `rsi(src, len)`: rma-based; `dn==0 ⇒ 100`, `up==0 ⇒ 0`; both zero ⇒ 100 per Pine (the Python twin gives 50; golden decides).
- `sma, sum, highest, lowest` (NaN until `len` bars), `stdev` (population/biased, as Pine), `crossover/crossunder`, `change`.
- `pivothigh/pivotlow(src, left, right)`: bar `t−right` is confirmed at bar t. Tie policy param `pivot_ties` (default: strictly greater than the left bars, ≥ the right bars; verify vs golden).
- `round_to_mintick(x)`: `floor(x/mintick + 0.5 + 1e-9) * mintick` (half-up, epsilon-guarded; verify vs golden).
- IST time/session helpers: `bar_minutes_ist(start|end)`, `is_new_session`, `is_last_bar_of_session`, `timeframe.change` for D and HTF.
- Causal `security` substitutes, supplied by the runner through `EngineContext` (engines never fetch; the runner builds them from the stored 1m bars with the D08 resample and reveals nothing later than the bar):
  - `ctx.prior_day(bar) -> PriorDay | None`: high/low/close of the previous completed trading session (`calendar_days`); `None` on the first session of a dataset.
  - `ctx.htf(bar, res) -> HtfStep(new_bar: bool, completed: Bar | None)`: `new_bar` = Pine `timeframe.change(res)`; `completed` = the HTF bar that closed just before this bar's HTF bar (given once, when `new_bar`). Pine `pivothigh(L, L)[1]` with lookahead_on = the pivot evaluated on the engine's own HTF buffers at `completed`.
  - `ctx.sub_bars(bar, res) -> list[Bar]`: finalized `res` bars with start in `[bar_start, bar_end)` (the partial one too inside `on_provisional`); `res` must be shorter than and divide the chart timeframe, else `ConfigError`.
  - `ctx.proxy_volume(bar) -> float | None`: front-month NIFTY future volume for the same bucket (D10); `None` when unavailable.

## Parity tiers (D16)
- **A** series: plots within 1e-6 absolute after warm-up (`warmup_bars`); report max abs error per series.
- **B** signals: identical signal bars, directions and events.
- **C** trades vs TradingView "List of trades": entry/exit time and price, reason, P&L; documented diffs.
Oracle priority: TradingView golden > PineTS (optional, NVS only) > Python twin (`reference/oracle`).

## Golden inputs
`fixtures/tv_golden/<engine>/{ohlc_plots.csv, trades.csv}`. Absent ⇒ tests skip and STATE lists "golden missing".
- Use TradingView's own exported OHLC as the engine input (removes vendor diffs). Chart timezone = Exchange (Asia/Kolkata); NVS on 5m.
- Comparator accepts "Export chart data" (ISO or unix `time`) and "List of trades" (two rows per trade, paired by Trade #). Export availability depends on the user's TradingView plan.
- `make parity E=<engine> [G=<dir>]` prints ≤30 lines: counts, first 5 diffs per tier, max abs error per series.
- Balu golden: proxy volume OFF (TWAP branch); prior-day and HTF aggregates derive from the supplied bars (flag differences). C09 creates `fixtures/tv_golden/BALU_DEBUG_PLOTS.pine.txt` (`plot(x, "dbg_<name>", display=display.data_window)` lines to append to a copy of the script; series lists are in `docs/pine/BALU-1|2|3.md`); C10 and C11 append theirs; the user exports once after C11. Stay ≤ 64 `plot*()` calls; if a series is missing from the export, set `display=display.all`.
