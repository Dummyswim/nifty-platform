# C11 · Balu 3: path history, panel, alerts, integration
effort: high · deps: C10 · reads: `docs/pine/BALU-3.md` · `docs/spec/04-pine-parity.md` (Golden inputs) · D14
pine: `reference/pine/Balu_Zone_Scalper_v2.pine` L770–895 (one view)
tools: view · bash (`make test`, `make parity`, `make bench`) · browser canvas · `task` for the full suite
**If short:** 1 path history · 2 panel + alerts · 3 snapshot/restore + properties · 4 bench + UI check · 5 docs + golden instructions.

**Goal.** Finish `pine.balu_zone`: path history, the 13-row panel, alerts; complete snapshot/restore; `ready=True`; verify in the UI; tell me what to export from TradingView.

**Do**
1. Steps 13–15 of the bar order (BALU-3): path history (`stateId = regimeIdx*9 + (flowState+1)*3 + locIdx`, 27 buckets, rules in order), the panel snapshot, alerts (regime flips with the per-session repeat replicated, divergences).
2. Complete the `Engine` per BALU-3 §Integration: plots union, `warmup_bars`, full `snapshot/restore` (every item listed there), `panel()`, `ready=True`, `docs/engines/balu.md` (≤40 lines: params, outputs, limits).
3. Append the C11 lines to `BALU_DEBUG_PLOTS.pine.txt`.
4. Tests per BALU-3 §Acceptance (C11). D14 properties on the 5m resample of the oracle CSV with 1m sub-bars supplied: batch == incremental == restart (random cut, JSON round-trip).
5. `make bench`: add the Balu engine and report bars/s (target ≥3,000). If lower: profile (cProfile, top 10), fix hot spots (plain floats, nothing pandas inside the bar loop), at most 2 iterations, then report the number.
6. Browser canvas on the oracle dataset: Balu is in the indicator panel; zones, key levels and markers render; the panel card shows 13 rows; no console errors.
7. In your reply, once: give me the one-time Balu golden export steps (`prompts/00-RUNBOOK.md` §Golden). Leave `golden_tv` untouched until I confirm the files exist.

**Acceptance.** BALU-3 §Acceptance (C11) met; `make parity E=pine.balu_zone` runs (says `golden missing` when the file is absent); `make bench` numbers recorded; `make check` green.
**Record in STATE:** engine id and `ready`, bench numbers, snapshot schema version, the debug-plots file path, Pine mismatches.
