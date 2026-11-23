# BALU-1 port map: `reference/pine/Balu_Zone_Scalper_v2.pine` L74–430 (inputs, core/session, level pool, Golden Line, Moving Line) → engine `pine.balu_zone`

Pine v6 indicator, 895 lines, intraday only. Pine is authoritative: if this map disagrees, follow Pine and log in STATE. Chunk C09 reads Pine **L74–430 only**. Maps: BALU-2 (L431–769), BALU-3 (L770–895).

## Params rule (applies to all three maps)
Every `input.*` in L74–164 becomes a `Params` field with the Pine default, min/max and group. Pure drawing options (`show*` for zones/labels/gold/CVD/panel, colours, `goldTint`, `panelPos`) go to the `ui` sub-model (excluded from `config_hash`). A toggle that gates a computed event or alert stays in `Params`: `showDiv`, `showFootprint`, `fpMarkTraps`, `fpAtZoneOnly`, `sweepConfOnly`, `useProb`, `showKeyLevels`, `kl*`, `useHtfLevels`. Plots are always emitted; `ui` only hides them. `goldProxySym` (TradingView symbol) becomes `proxy_volume_instrument` (front-month NIFTY future from the Kite master, D10) and is used only when `goldProxy` is true.

## Inputs → Params (defaults; verify against L74–164)
- Zone Map: `sessionStr` "0915-1530" · `swingLen` 3 (1–10) · `zoneTiers` 2 (1–4) · `zoneThickATR` 0.35 · `capBaseATR` 2.5 · `capStepATR` 2.5 · `orMinutes` 15 · `dedupeATR` 0.50 · `minSpaceATR` 1.0 · `pruneATR` 14.0 · `keepMitigated` false.
- HTF: `useHtfLevels` true · `htfMode` Auto|15m|30m|1H|2H|4H|Daily (Auto) · `htfPivotLen` 2.
- Golden: `goldSource` "VWAP (session)"|"Daily Pivot (PP)"|"EMA" · `goldEmaLen` 50 · `goldDeadATR` 0.25 · `goldProxy` false.
- Moving Line: `cvdSource` Auto|Real Volume|Price Action · `flowWarmBars` 10 · `flowSmoothLen` 5 · `flowSlopeLen` 5 · `flowDead` 0.30 · `showDiv` true · `divPivotLen` 5 (2–20).
- Intrabar (BALU-2): `showFootprint` true · `fpLtf` "1" · `fpMinSubBars` 3 · `fpImbal` 0.50 · `fpEffMult` 1.3 · `fpEffLen` 20 · `fpAtZoneOnly` true · `fpMarkTraps` true · `sweepConfOnly` true · `sweepConfBars` 3.
- Path History (BALU-3): `useProb` true · `probHorizon` 20 · `probMinN` 100.
- Key Levels: `showKeyLevels` true · `klPDHL` true · `klPDC` true · `klPivot` false · `klOR` true.
- Panel: `zoneProxATR` 0.35 (Param: it drives location).
Constants: `atr = ta.atr(14)` L168 (**continuous across sessions**; `rma` of the true range, first TR = high−low, seeded by SMA(14); not the session-reset ATR of NVS) · `rangeBar = max(high−low, mintick)` L169 · `tfMin = max(tf_minutes, 1)` L170.

## Session and anchors (L171–209)
`inSession` L175 = bar START inside 09:15–15:30 IST (5m: last bar starts 15:25). `newTradingDay = timeframe.change("D")` L176. `isNewSession = inSession and (not inSession[1] or newTradingDay)` L177. `sessionEnds` L178 = last in-session bar (used in BALU-3). Prior day L181: previous **completed** session's high/low/close (calendar of trading days, D09; NaN on the first session of a dataset) → `pp=(pdH+pdL+pdC)/3` L184, `r1=2pp−pdL` L185, `s1=2pp−pdH` L186. Anchors L188–209: on `isNewSession` set `orHigh=orLow=sessHi=sessLo` from this bar and `dayLen=1`; else if `inSession`: `dayLen += 1`, extend `sessHi/sessLo`, and while `dayLen ≤ orBars` extend `orHigh/orLow`. `orBars = max(1, ceil(orMinutes/tfMin))` L194. Out-of-session bars change nothing.

## Structure sources and HTF (L210–224)
`sPH/sPL = pivothigh/low(high/low, swingLen, swingLen)` L213–214 (confirm `swingLen` bars late; the value is the pivot bar's price). `autoHtfRes` L216: tf ≤3 → 15, ≤5 → 30, ≤15 → 60, ≤60 → 240, else D; `htfRes` L217 maps the mode (2H = 120). First bar: if `useHtfLevels` and HTF is not strictly longer than the chart ⇒ engine error `HTF_NOT_HIGHER` (L218–220). `htfPH/htfPL` L222–223 = pivot of the **previous completed HTF bar** (`pivothigh(htfPivotLen, htfPivotLen)[1]` with lookahead_on): constant for the whole HTF bar, identical live and on reload. `htfNewBar` L224 = first chart bar of each HTF bar. HTF bars are session-anchored resamples of the 1m store (D08; e.g. 30m = 09:15, 09:45…; 240m = 09:15–13:15 and 13:15–15:30; D = one per session). The runner supplies completed HTF bars via `EngineContext`.

## Level pool (L226–307)
Parallel arrays `lvlPrice`, `lvlIsHigh`.
- `f_addLevel(p, isHigh)` L232: skip if `p` is NaN/≤0 or `atr` invalid; `tol = atr*dedupeATR`; find the **first** entry with the same `isHigh` and `|price−p| ≤ tol`; if found set it to `(old+p)/2` (plain average), else append.
- `f_prunePool()` L247: `far = atr*pruneATR`; loop **from the end down to 0** removing entries with `|price−close| > far`; then while size > **60** drop the oldest.
- Adds on the confirmed bar, in this order (L258–272): `sPH(high)`, `sPL(low)`; if `useHtfLevels and htfNewBar`: `htfPH(high)`, `htfPL(low)`; if `isNewSession`: `pdH(high)`, `pdL(low)`, `pdC(high)`, `pdC(low)` (PDC is added twice, as both flags, so it never merges with itself); if `dayLen == orBars+1`: `orHigh(high)`, `orLow(low)`; finally `f_prunePool()`.
- Queries (used by BALU-2): `f_nearestAbove(ref, gap, used, space)` L276 = lowest pool price `v > ref+gap` with no `used` price within `space` (`|used−v| ≤ space`); `f_nearestBelow` L292 = highest `v < ref−gap`, same rule. Flags are ignored by queries. Strict `<`/`>` for ties.

## Golden Line (L308–359)
`volSeen` L314–315: sticky across the whole run (not reset per session). Per-session accumulators reset on `isNewSession`, accumulate only `inSession`: `gChartPV += hlc3*nz(vol)`, `gChartW += nz(vol)`, proxy equivalents with `nz(proxyVol)`, `gSumP += hlc3`, `gCnt += 1`.
`vwapVal` L337 = `gChartW>0 ? PV/W : (goldProxy and gProxyW>0) ? proxyPV/proxyW : gCnt>0 ? gSumP/gCnt : NaN` (the branch can switch mid-session when volume first appears: replicate). `goldAnchorTxt` L338 (panel text: VWAP | Proxy weighted | Proxy unavailable: TWAP | TWAP (no vol) | Daily PP | EMA). `goldVal` L339 = vwapVal | `pp` | `ema(close, goldEmaLen)` (continuous EMA).
`goldDead = atr*goldDeadATR` L342. `goldState` L343 resets to 0 on `isNewSession`; `close > goldVal+goldDead ⇒ 1`, `close < goldVal−goldDead ⇒ −1`, else retained (NaN compares false). `goldSlope = dayLen>flowSlopeLen ? goldVal−goldVal[flowSlopeLen] : 0` L351. `regimeIdx` L352 = state>0 ? (slope≥0 ? 2 : 1) : state<0 ? (slope≤0 ? 0 : 1) : 1 (2 BULL, 1 NEUTRAL, 0 BEAR); text L353.
Plot L357: `golden` = NaN on the first bar of each session, else `goldVal` (line break).

## Moving Line (L360–430)
`useRealVol` L363 = `cvdSource=="Real Volume" or (Auto and volSeen)`; `closePos = (close−low)/rangeBar` L364; `deltaSize = useRealVol ? nz(vol) : rangeBar` L365; `barDelta = deltaSize*(2*closePos−1)` L366. `cvd` L368: on `inSession`, `isNewSession ? barDelta : cvd+barDelta`. `cvdHi/cvdLo` L373–377: reset to `cvd` on `isNewSession`, else running max/min. `priceSpan = max(sessHi−sessLo, mintick)`; `flowReady = dayLen ≥ flowWarmBars and (cvdHi−cvdLo) > 0` L381; `movingLine = sessLo + (cvd−cvdLo)/max(cvdHi−cvdLo,1e-9)*priceSpan` L384; plot only when `flowReady` (step line).
Flow L388–391: `cvdSlope = sum(ema(barDelta, flowSmoothLen), flowSlopeLen)` (EMA continuous across sessions); `slopeSd = stdev(cvdSlope, 100)` (**population**, NaN until the window is full); `flowZ = slopeSd>0 ? cvdSlope/slopeSd : 0` (so during warm-up `flowZ=0`, not NaN); `flowState = flowZ>flowDead ? 1 : flowZ<−flowDead ? −1 : 0`.
Divergence L397–430: `ph/pl = pivothigh/low(high/low, divPivotLen, divPivotLen)`; `lastPH/lastPHcvd/lastPL/lastPLcvd` reset to NaN on `isNewSession`. If `showDiv and dayLen > 2*divPivotLen and ph valid`: `c = cvd[divPivotLen]` (raw cvd at the pivot bar); `bearDiv = lastPH valid and ph > lastPH and c < lastPHcvd`; then `lastPH=ph, lastPHcvd=c`. `bullDiv` mirrors with `pl < lastPL and c > lastPLcvd`. Signalled on the confirming bar, never back-dated (events carry `pivot_bar_start` and `known_bar_start`).

## Outputs
Plots: `atr` (hidden) · `golden` · `gold_state` · `regime_idx` · `cvd` · `moving_line` (NaN unless `flowReady`) · `flow_z` · `flow_state` · `day_len` · `or_high` · `or_low` · `pool_size`. Events: `divergence {side, pivot_bar_start, known_bar_start}`. Key-level overlays are BALU-2. Panel rows are BALU-3.

## Golden debug plots (C09 creates `fixtures/tv_golden/BALU_DEBUG_PLOTS.pine.txt`)
One `plot(x, "dbg_<name>", display=display.data_window)` line each for `atr, goldVal, goldState, regimeIdx, cvd, movingLine, flowZ, flowState, flowReady, dayLen, orHigh, orLow, lvlPrice.size()`. C10 and C11 append theirs, so the user exports once after C11. Keep the copy ≤ 64 `plot*()` calls; if a series is missing from the export, switch it to `display=display.all`.

## Acceptance (C09)
Unit tests on synthetic bars: pool merge-average, prune-from-end, cap 60; PDC dual add; OR window boundary (`dayLen == orBars+1`); HTF resample and once-per-HTF-bar add; hysteresis; session resets; `flowReady` gating; population stdev; `flowZ=0` warm-up; divergence lag. Tier-A parity on the series above when the golden exists (skip otherwise). Interfaces for C10: `LevelPool`, `SessionState`, `regime_idx`, `flow_state`.
