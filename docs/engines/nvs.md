# Engine `pine.nvs_scalper` (v1): port of `Nifty_VWAP_Spread_Scalper.pine` L29–358

Code: `backend/src/nifty/engines/nvs/{params,engine}.py`. Port map: `docs/pine/NVS.md`. 5m, intraday, mintick from the instrument (never invented).

**Params** (`NvsParams`): every Pine input at its default, snake_case (`ema_fast_len`, `rsi_long`, `min_dev_atr`, `target_r`, `entry_start_hm` …). Extras: `commission_pct` (0.0125, emulator), `anchor_mode` `signal_close` (Pine) | `fill_price` (twin: re-anchor stop distance/target to the fill open, decline if `risk<=0`, `risk>1.25*maxRisk*ATR` or the cost rule fails; a declined fill releases the day's trade count), `ema_seed` `first`|`sma`. `ui` (labels, bands, colours) is outside `config_hash`.

**Outputs.** Plots: `vwap ema_fast ema_slow buy_near buy_far sell_near sell_far stop target`. Events: `signal` (close, stop, target, risk_pts, why) · `entry` (fill open) · `exit` (reason, r, price) · `stop_update` (BE ratchet). Overlays: signal/entry/exit `marker`, stop and target `line` from the signal bar to the exit time (initial levels). Trades via `BrokerEmulator` (tv mode); `r_multiple` is the script's net/risk (costBps), exit reasons `TP SL BE_STOP VWAP_LOSS STRETCH_STALL RSI_FADE TIME EOD SESSION_END`. Panel: 8 rows as the Pine dashboard.

**Regenerate / check:** `make parity E=pine.nvs_scalper` · `make test T=backend/tests/unit/engines/nvs` · twin log: `python reference/oracle/vwap_scalper.py backtest --csv reference/oracle/data/nifty_1m.csv --minutes 5`.

**Oracle result** (5m session-anchored resample of `nifty_1m.csv`, `tv` mode, `signal_close`): entries 15/15 (fill bar, side, price ±0.01); exits 14/15 (same bar and reason).
Diffs vs the twin, all expected:
- 11-03 long (entry 12:30): TP at 23702.90 on 13:15 vs twin 23702.38 on 13:05. The twin re-anchors the target to the fill price (Pine anchors to the signal close), so the twin's lower target hits two bars earlier. Same entry, same reason.
- Every TP/SL/BE price differs by a few points for the same reason (stop/target = signal close ∓ risk, rounded to the mintick; twin is unrounded and fill-anchored). Rs differ accordingly (e.g. −1.212 vs −1.213 R, TP 1.017 vs 1.159 R).
- EMA seeded with the first close (`ema_seed=first`), RSI both-zero = 100, flips counted per Pine window: none changed an entry on this data.
- The twin keeps the trailing partial 5m bucket (11-16 14:45, 4 of 5 bars); the runner emits only finalized bars, so it is dropped. No entry or trade is affected (entries end 14:45 bar end; the last trade closed 12:30).
- Exit timestamps: close-filled exits (`EOD`, `SESSION_END`) are stamped with the bar END by the emulator; the comparator maps them to the bar start (twin convention).

**Pine ≠ port:** none intended. TradingView golden still decides `ema_seed`, `round_to_mintick`, RSI both-zero and the first-bar ATR (see STATE Open issues).
