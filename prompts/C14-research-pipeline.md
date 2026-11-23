# C14 · Research runs, statistics, verdict, UI
effort: high · deps: C13, C06 · reads: `docs/spec/07-research.md` (Persistence, Statistics and verdict, Frontend) · `docs/spec/05-backend.md` (Jobs, API) · D18
research prompt (view_range only): §9 L260–285 · §11 L300–332 · §12 L333–349
pine: — · tools: bash (`make test`, `make e2e`) · browser canvas · create/edit · `task` for the full suite
**If short:** 1 runs + labels persistence · 2 statistics · 3 verdict · 4 API + UI.

**Goal.** Reproducible research runs with honest statistics and a verdict that is allowed to say "edge not established".

**Do**
1. Alembic `research_runs` (snapshot_id, config_hash, seed, splits, variant list, code version, result JSON) and `research_labels` (idempotency key unique on `(engine_id, config_hash, instrument_id, signal_bar_start, side)`).
2. Job `research_run {snapshot_id, variants, experiments, cost_pts, seed}` in the C04 worker: checkpoint per session, resumable, failures stored (never an empty success).
3. `nifty.analytics.research` (pure): chronological split 50/25/25 **by session** with purge ≥ max-hold across boundaries; anything fitted uses only allowed data; every tested variant recorded. Per (variant, experiment): trades, outcome mix incl. ambiguous/interrupted, net expectancy in points after `cost_pts`, session-clustered bootstrap 95 % CI (fixed seed, 2,000 resamples default), leave-one-session-out.
4. Verdict: `candidate` only when, on the untouched evaluation split, the CI lower bound is > 0, validation agrees in sign and it survives leave-one-session-out, **and** sessions ≥ 60. Fewer than 60 sessions ⇒ `inconclusive` with "insufficient sessions" (our reading of spec/07; log it). Otherwise `edge_not_established`. Thresholds are our choice and are stored with each run. The verdict never claims proof.
5. API `research/runs` (create → job, list, get with variant tables and verdict, labels paged). Research page: run form, variant table with CI bars (ECharts), outcome mix, a verdict banner listing which conditions passed or failed, and a drilldown to a label on the index chart (EMA9/21 + anchor lines, markers for watch/armed/entry/exit/target/stop/invalidation, diagnostics panel, label `BEARISH INDEX / PUT CANDIDATE` or its bullish mirror). Never write "three independent confirmations".
6. Tests: split and purge leave no leakage across boundaries · bootstrap deterministic for a fixed seed and resamples whole sessions (hand-checked tiny set) · leave-one-session-out · verdict rules table-tested on synthetic results (strong edge at 80 sessions ⇒ `candidate`; noise ⇒ `edge_not_established`; 17 sessions ⇒ `inconclusive`) · same key re-run ⇒ same result, no duplicate labels · job failure surfaced.

**Acceptance.** Oracle dataset end-to-end through the job and the UI: verdict `inconclusive` with "insufficient sessions"; `make check` and `make e2e` green (add a Research smoke).
**Record in STATE:** thresholds, seed policy, API shapes, verdict reading, run reproducibility notes.
