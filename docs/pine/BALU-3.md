# BALU-3 port map: `reference/pine/Balu_Zone_Scalper_v2.pine` L770–895 (path history, panel, alerts) + whole-engine integration

Pine is authoritative: if this map disagrees, follow Pine and log in STATE. Chunk C11 reads Pine **L770–895** (and the bar-order table below), then integrates the engine written in C09/C10.

## Path history (L770–846; descriptive statistics, not a forecast)
`stateId = regimeIdx*9 + (flowState+1)*3 + locIdx` L776 (27 buckets). State: per-bucket int arrays `hitUp, hitDn, timedOut, bothHit, sessionCut, sampleDays` (0) and `lastSampleDay` (NaN); scalars `prevState, pState, pUp, pDn, pBar` (NaN). `bar_index` = the engine's own finalized-bar counter.
Every confirmed bar when `useProb`, in this order (L791–829):
1. If an episode is open (`pState` set) and (`isNewSession` or not `inSession`): `sessionCut[pState] += 1`, close the episode (no resolution with tomorrow's gap).
2. If `isNewSession` or not `inSession`: `prevState = NaN`.
3. If an episode is open: `up = high ≥ pUp`, `dn = low ≤ pDn`. Both ⇒ `bothHit++`; else up ⇒ `hitUp++`; else dn ⇒ `hitDn++`; else if `bar_index − pBar ≥ probHorizon` ⇒ `timedOut++`; else if `sessionEnds` ⇒ `sessionCut++`; else keep it open. Any counted outcome closes the episode. The start bar is never evaluated (the start step comes later in the same bar); a hit on bar `H` beats the timeout.
4. `changed = prevState valid and stateId ≠ prevState`. `realBarriers = nextUp, nextDn valid and nextDn < close < nextUp and neither projected`.
5. If `inSession and not sessionEnds and changed and realBarriers` and no episode is open: open one (`pState=stateId, pUp=nextUp, pDn=nextDn, pBar=bar_index`); `sampleDay = session date`; if `lastSampleDay[stateId]` is NaN or ≠ `sampleDay`: `sampleDays[stateId] += 1`, set it. A transition while busy or without real barriers is skipped, never queued.
6. If `inSession`: `prevState = stateId`.
Stats L831–845 use `statsState = stateId` (confirmed bar; on a forming bar the previous confirmed `stateId`): `nResolved = nUp+nDn`; `nFinished = nResolved+nTimeout+nBoth+nCut`; `nPending = (episode open and pState == statsState) ? 1 : 0`; `resolvedShare = 100*nUp/nResolved`; `historyLo = 100*nUp/nFinished`; `historyHi = 100*(nUp+nBoth+nCut)/nFinished`; `probReady = useProb and nFinished ≥ probMinN`. Row text must keep the "not a CI" and "Not established" wording (D18).

## Panel (L847–884; `panel()` = 13 rows `{label, value, role}`, evaluated for the latest bar)
0 Regime (BULL/NEUTRAL/BEAR; role bull/neutral/bear) · 1 `Flow (volume proxy)` if `useRealVol` else `Flow (range proxy)` (RISING/FALLING/FLAT) · 2 Location · 3 To Supply = `nextUp−close` rounded to 1 dp (+" (proj)"), "—" if none · 4 To Demand = `close−nextDn` · 5 History (closed state) = `nFinished done / nPending open / sampleDays[statsState] days` or OFF · 6 `Up / Dn / Timeout / Both / Cut` counts or "—" · 7 `Up first | resolved only` = `"<resolvedShare 0dp>% (n=<nResolved>)"` if `probReady and nResolved ≥ probMinN`, else "Too few resolved episodes" (OFF if `useProb` false) · 8 `Up by H | history bounds` = `"<lo>..<hi>% (not a CI)"` if `probReady`, else "Too few finished episodes" · 9 `Forecast / edge / effective n` = "Not established" · 10 Divergence (BEARISH/BULLISH/—) from this bar's flags · 11 `Pressure | Gold` = `fpTxt + " | " + goldAnchorTxt` with `fpTxt` = "n/a (LTF unavailable/invalid)" if `not fpValid`, BUY/SELL, or BUY?/SELL? when the last evaluation was provisional, else "—" · 12 Sampling = `Transitions; real zones; H=<probHorizon>`.
Panel strings are display only (not parity-compared). Use round-half-up for `math.round`.

## Alerts (L885–895; events `alert`, confirmed, at bar close)
`goldFlipUp = regimeIdx==2 and prev regimeIdx != 2`; `goldFlipDn = regimeIdx==0 and prev != 0` (not session-aware: the per-session `goldState` reset makes them fire again each session; replicate; no flip on the first bar). Also `bearDiv` and `bullDiv`. Names: "Regime Turned Bullish", "Regime Turned Bearish", "Bearish Divergence", "Bullish Divergence". Pressure and sweep alerts are in BALU-2.

## Whole-engine bar order (all on the finalized bar; Pine is top-to-bottom)
1 session flags and anchors L175–209 → 2 pivots `sPH/sPL` and HTF step L213–224 → 3 pool adds and prune L258–272 → 4 golden L314–357 → 5 moving line L363–395 → 6 divergence L397–430 → 7 zone housekeeping L470–490 → 8 zone rebuild L493–566 → 9 key levels L604–619 → 10 location L629–660 → 11 pressure L673–693 → 12 sweeps L696–755 → 13 path history L776–845 → 14 panel snapshot → 15 alerts L890–895. Increment the bar counter at the start of step 1.

## Integration (C11)
- Complete `Engine` per `docs/spec/01-contracts.md`: `Params` (+`ui`), `plots` list (union of BALU-1/2 plus `state_id, n_up, n_dn, n_timeout, n_both, n_cut, n_pending`), `warmup_bars = 100 + flowSlopeLen`, `on_bar`, `on_provisional` (pressure only), `snapshot/restore` (JSON-serialisable: rolling windows for ema/rma/sma/stdev and pivots, pool, zones with ids and the id counter, sweep machines and done lists, path-history arrays and open episode, session anchors, `volSeen`, `goldState`, divergence memory, previous `regimeIdx`/`stateId`), registry entry `pine.balu_zone`, `docs/engines/balu.md` (≤ 40 lines: params, outputs, limits).
- Property tests (D14): batch == incremental == restart (random cut, JSON round-trip) on the 5m session-anchored resample of `reference/oracle/data/nifty_1m.csv`, with 1m sub-bars supplied. `make bench`: report bars/s (target ≥ 3,000).
- Limits to record in the doc: needs 1m sub-bars for pressure; prior-day and HTF values come from the supplied dataset (the first session has no prior day); proxy volume only with a front-month future; EARLY alerts are live only; path-history counts depend on the history length supplied.

## Golden debug plots (append to `fixtures/tv_golden/BALU_DEBUG_PLOTS.pine.txt`)
`stateId, nUp, nDn, nTimeout, nBoth, nCut, nPending, sampleDays.get(statsState)`. After this chunk tell the user to export once: chart data (Exchange timezone) of the debug-plots copy, proxy volume OFF, into `fixtures/tv_golden/balu/ohlc_plots.csv`.

## Acceptance (C11)
Unit tests: episode start/skip rules (first bar of a session, busy, projected barriers, `sessionEnds`), both-hit, up-only, dn-only, hit at bar `H` vs timeout at `H`, session cut (new session and `sessionEnds`), one `sampleDays` increment per bucket per day, stats arithmetic, panel row order and strings, regime-flip alerts (including the per-session repeat). Full-engine property tests above green; `make parity E=pine.balu_zone` runs (skips when the golden is missing and says so).
