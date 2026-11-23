# C10 · Balu 2: zones, key levels, location, pressure, sweeps
effort: high · deps: C09 · reads: `docs/pine/BALU-2.md` (BALU-1 interfaces are in STATE; do not reread BALU-1) · D14
pine: `reference/pine/Balu_Zone_Scalper_v2.pine` L431–769 in three views: L431–576, L577–663, L664–769
tools: view (those ranges) · grep · bash (`make test`) · `task` for the full suite
**If short:** 1 zones + key levels · 2 location · 3 pressure + `on_provisional` · 4 sweeps · 5 debug plots.

**Goal.** Steps 7–12 of the bar order appended to `STEPS`: zone and sweep state machines, overlays, provisional pressure.

**Do**
1. New modules `zones.py`, `keylevels.py`, `location.py`, `pressure.py`, `sweeps.py`, appended to `STEPS`. Do not edit C09 modules except to expose what BALU-2 needs (record each such edit in STATE).
2. Zones keep creation order; location loops overwrite by array order (BALU-2). Overlays per BALU-2: event-sourced zones (`ver`, `meta.status`), key-level `hline` rails, markers on the **confirming** bar for sweeps.
3. Pressure reads `ctx.sub_bars(bar, res)`. An `fpLtf` that does not divide the chart timeframe ⇒ `ConfigError`. `on_provisional(bar)` computes pressure on the partial sub-bars against the last confirmed zones only, emits `press_buy_early` / `press_sell_early` flagged provisional, and must not touch zones, sweeps or path state (test: `snapshot()` unchanged).
4. Append the C10 lines to `BALU_DEBUG_PLOTS.pine.txt` (BALU-2 §Golden debug plots).
5. Tests per BALU-2 §Acceptance (C10) on hand-built synthetic bars derived from the Pine semantics. D14 properties on the extended engine. Keep `ready=False`.

**Acceptance.** BALU-2 §Acceptance (C10) met; `make test T=backend/tests/unit/engines/balu` green; the `run-engine --allow-unready` command from C09 still runs and now emits zone overlays; `make check` green.
**Record in STATE:** new modules, the C09 edits you had to make, overlay ids and versioning scheme, provisional events.
