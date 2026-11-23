# C03 · NVS port + parity harness
effort: high · deps: C02 · reads: `docs/pine/NVS.md` · `docs/spec/04-pine-parity.md` (Parity tiers, Golden inputs) · `docs/spec/03-execution.md` (BrokerEmulator) · `docs/SOURCES.md`
pine: `reference/pine/Nifty_VWAP_Spread_Scalper.pine` L29–358, read in 3 ranges while you implement · oracle: `grep -n` in `reference/oracle/vwap_scalper.py` only, never read it whole
tools: view (ranges) · grep · bash (`make test`, `make parity`) · `task` for the full suite

**Goal.** Engine `pine.nvs_scalper` with TradingView semantics, and the parity harness every later port reuses.
**If short:** 1 engine + unit tests · 2 harness · 3 oracle parity · 4 docs.

**Do**
1. Learn the oracle's conventions first: `grep -n "entry_ts\|resample\|signal" reference/oracle/vwap_scalper.py | head -40` (is `entry_ts` the signal bar or the fill bar? how is a partial trailing bucket handled?). Put the answers in STATE Facts.
2. Engine in `backend/src/nifty/engines/nvs/` exactly per `docs/pine/NVS.md`: Params (Pine defaults; `ui` split; `anchor_mode` `signal_close|fill_price`; `ema_seed` `first|sma`), the 8-step bar order, exit-reason priority, BE ratchet, accept/reject rules, TWAP anchor when `volume_kind=absent`. Trades through `BrokerEmulator` in `tv` mode. Outputs: plots; events (`signal entry exit stop_update`); overlays for entries, stop and target (webapp L205–218): stop/target = `line` elements from the signal bar to the exit bar, entry/exit = `marker`.
3. Unit tests per rule on hand-built bars (each exit reason, accept and reject, BE ratchet, stale `inPos` after SESSION_END, cooldown and day limits) + the D14 properties via the runner. Register the engine with `ready=True`.
4. `nifty.parity` (`compare.py`, `tv_io.py`): Tier A/B/C comparators; loaders for TradingView "Export chart data" and "List of trades" (spec/04) and for `reference/oracle/logs/scalper_trades.csv`. CLI `parity --engine ID [--golden DIR] [--oracle PATH]` prints ≤30 lines; wire `make parity`. No golden ⇒ prints `golden missing`, exit 0, noted in STATE.
5. Oracle parity: input = 5m session-anchored resample of `reference/oracle/data/nifty_1m.csv` (decide the trailing partial bucket using step 1 and log it); `tv` mode, `anchor_mode=signal_close`. Expect all 15 entries (time and price, Tier B) and ≥14/15 exits (same bar and reason). Explain every diff in `docs/engines/nvs.md` (≤40 lines: params, outputs, diffs vs Pine and twin, regenerate command). Behaviour that differs from Pine also goes under STATE Deviations.

**Acceptance.** `make test T=backend/tests/unit/engines/nvs` green · `make parity E=pine.nvs_scalper` shows entries 15/15 and exits ≥14/15 · `python -m nifty.cli run-engine --engine pine.nvs_scalper --symbol "NIFTY 50" --timeframe 5m --no-persist` runs · `make check` green.
**Tell me** how to export the TradingView golden (`prompts/00-RUNBOOK.md` §Golden). Keep `golden_tv=none` until I confirm the files exist.
**Record in STATE:** engine id and Params location, parity CLI + harness API, oracle conventions, accepted diffs.
