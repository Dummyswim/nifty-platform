# C09 · Balu 1: params, session, level pool, Golden Line, Moving Line
effort: high · deps: C03 · reads: `docs/pine/BALU-1.md` · `docs/spec/04-pine-parity.md` · D14 D15 D25
pine: `reference/pine/Balu_Zone_Scalper_v2.pine` L74–430 in four views: L74–209, L210–257, L258–357, L358–430
tools: view (those ranges) · grep · bash (`make test`, `make parity`) · `task` for the full suite
**If short:** 1 Params + session + pool · 2 Golden Line · 3 Moving Line + divergence · 4 debug-plots file + parity test.

**Goal.** The first third of `pine.balu_zone`: everything up to the divergence signal, laid out so C10 and C11 extend it without editing it.

**Do**
1. Package `backend/src/nifty/engines/balu/`: `params.py` (every input L74–164 → `Params` with Pine defaults, min/max, group; `ui` split per BALU-1 "Params rule"), `state.py` (SessionState + JSON-serialisable rolling windows), `levels.py` (`LevelPool`), `golden.py`, `moving_line.py`, `engine.py` (`BaluZoneEngine`, `default_timeframe="5m"`, an ordered `STEPS` list with the 15 slots of BALU-3's bar order; C09 fills steps 1–6, later chunks append). Register with `ready=False`.
2. Implement from the Pine ranges as you read them, using BALU-1 as the map. Pine wins over the map on any mismatch (log it in STATE). Use pinekit; a missing primitive is added there with a hand-computed known-answer test (list it in STATE).
3. Aux data only through `ctx.prior_day`, `ctx.htf`, `ctx.proxy_volume` (spec/04). The first session has no prior day.
4. Create `fixtures/tv_golden/BALU_DEBUG_PLOTS.pine.txt` per BALU-1 §Golden debug plots.
5. Tests per BALU-1 §Acceptance (C09) on synthetic bars, written from the Pine semantics, never from your implementation's output. D14 properties for steps 1–6 through the runner.
6. Tier-A parity test for the C09 series against `fixtures/tv_golden/balu/ohlc_plots.csv`; it skips with a message when the file is absent (it will be until after C11).

**Acceptance.** BALU-1 §Acceptance (C09) met; `make test T=backend/tests/unit/engines/balu` green; `python -m nifty.cli run-engine --engine pine.balu_zone --allow-unready --symbol "NIFTY 50" --no-persist` runs on the oracle data; `make check` green.
**Record in STATE:** package layout, the `STEPS` contract, `LevelPool` / `SessionState` / `regime_idx` / `flow_state` interfaces, pinekit additions, Pine mismatches.
