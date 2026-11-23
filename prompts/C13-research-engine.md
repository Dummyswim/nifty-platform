# C13 · Research engine: features, baselines, armed-resumption, outcomes
effort: high · deps: C03 · reads: `docs/spec/07-research.md` (all) · `docs/spec/03-execution.md` (`resolve_barriers`) · `docs/spec/04-pine-parity.md` (pinekit)
research prompt (view_range only): `reference/src/research-prompt.md` §6 L132–190 · §7 L191–223 · §8 L224–259
pine: — · tools: view (ranges) · bash (`make test`) · ask_user (genuine product choices only) · `task` for the full suite
**If short:** 1 features + baselines · 2 armed doc + state machine · 3 outcomes · 4 tests + report.

**Goal.** Engine `research.distance_entry_v1`: causal features, three named baselines, the armed-resumption setup and barrier outcomes. Paper only; no order code.

**Do**
1. Write `docs/engines/research-armed.md` first (≤40 lines): formation, direction, trigger level, invalidation, timeout, cancellation, rearming, from §7 and spec/07. ASK (one question at a time) only about choices the prompt leaves open **and** that change behaviour; decide the rest and log it in STATE.
2. `backend/src/nifty/engines/research/`:
   - `features.py`: spec/07 Features, causal and finalized-bar only; `atr_sess`; anchor TWAP vs VWAP chosen by `volume_kind`, labelled; `D E M`, derived gaps, rates with k=3 (never bridging the session reset; zero or invalid `A` ⇒ NaN, never infinity).
   - `baselines.py`: the three named variants. Log the anchor-crossover interpretation in STATE Open issues.
   - `armed.py`: the state machine from your doc; `outcomes.py`: via `resolve_barriers` (`TARGET_FIRST | STOP_FIRST | TIME_EXIT`, ambiguous bars and interruptions kept in the denominators; MAE, MFE, time-to-barrier, first-minute adverse move, holding time, drawdown, each with its definition and resolution limits).
   - `engine.py`: id `research.distance_entry_v1`, `default_timeframe="1m"`; Params (targets 10/20 as separate experiments, stop, max hold, entry window, `cost_pts`, baseline name); events `research.watch|armed|entry|exit|invalidated`; `panel()` diagnostics (D, E, M, rates, A, anchor kind); plots EMA9, EMA21, anchor. Register `ready=True`.
3. Index-only: no option P&L here; points and R only (UnitMismatch applies).
4. Tests: feature known answers computed by hand · zero or invalid ATR ⇒ NaN · rates do not cross sessions · each baseline's trigger and non-trigger · armed lifecycle (arm, invalidate, expire, one rearm, cancel) · outcomes (target first, stop first, both hit in one bar ⇒ `STOP_FIRST` + `ambiguous_bar`, time exit, session cut) · D14 properties and future-bar immunity through the runner · duplicate, out-of-order and zero-range bars.
5. Run on the oracle 1m data: print counts per baseline × experiment × outcome (≤20 lines). No performance claims.

**Acceptance.** `make test T=backend/tests/unit/engines/research` green; `python -m nifty.cli run-engine --engine research.distance_entry_v1 --symbol "NIFTY 50" --no-persist` runs; `make check` green.
**Record in STATE:** engine id, Params location, event types, the armed-spec doc path, interpretations and open issues.
