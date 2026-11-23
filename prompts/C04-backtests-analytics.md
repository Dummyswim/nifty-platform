# C04 · Jobs, backtests, audit, analytics, export
effort: med · deps: C03 · reads: `docs/spec/05-backend.md` (Jobs, Tables, API) · `docs/spec/03-execution.md` (modes, costs) · D07 · webapp prompt L232–283 (view_range: Backtesting, Audit, Analytics)
pine: — · tools: bash (`make test`, `make bench`) · create/edit · `task` for the full suite

**Goal.** A backtest = an engine over a snapshot → persisted trades → audit rows → analytics → export, all through jobs.

**Do**
1. One Alembic revision: `jobs`, `backtests`, `trades` (spec/05; `user_id` default 1). Tests: idempotency key returns the existing job, `SKIP LOCKED` with two workers, stale-job requeue, failure stored with a short error (never an empty "success").
2. `nifty.worker` (`python -m nifty.worker`): poll loop, heartbeat, handler registry; enable the compose profile `worker`.
3. Handler `backtest` {engine_id, params, snapshot_id | range, timeframe, mode `tv|conservative`, qty, cost_pts}: `run_batch` → persist run + trades → store the summary. Index-level trades in points; option mapping arrives in C12.
4. `nifty.analytics.metrics` (pure; hand-computed fixtures): win rate · profit factor (no losses ⇒ null + flag) · total P&L · expectancy · max drawdown (peak-to-trough on cumulative net points) · max consecutive wins/losses · Sharpe = mean/stdev (sample) of per-session net P&L × √252, rf = 0, always returned with `n_sessions` and `low_n` when < 30 (our definition; document it). Units explicit: `_pts` for index, `_inr` only for option paper trades.
5. Audit `GET backtests/{id}/audit/{trade_id}`: trade, entry/stop/target/exit levels, a ±N-bar window, events in range, exit reason. Fields required by webapp L246–264 (strike and option type are null for index trades; SL hit, target hit).
6. Export `GET backtests/{id}/export?fmt=csv|xlsx|json` (openpyxl; unit in each header).
7. API per spec/05: `engines` (+ JSON Schema), `engines/{id}/run` (job), `backtests` (create, list, get, `trades`, `analytics`), `datasets/import` (CSV upload through the C01 importer), `plots`, `events`, `overlays`. Then `make api-types`.
8. `make bench`: replay of ~100k generated 1m bars (oracle sessions tiled onto consecutive weekdays; label the data synthetic, never store it) through the NVS engine; print bars/s and peak RSS. Report; don't tune yet.
9. CLI `backtest run --engine ID --symbol S --timeframe 5m --mode tv` prints metrics (≤20 lines).

**Acceptance.** NVS backtest on the oracle dataset via CLI and via an API job: 15 trades; net points compared with `reference/oracle/logs/scalper_trades.csv` with the cost-model difference documented; the same job key returns the same result; exports open (`python -c` row counts); `make check` and `make bench` run.
**Record in STATE:** job kinds, API routes, metric definitions, bench numbers.
