# Research engine `research.distance_entry_v1` (C13 engine · C14 runs, statistics, UI)

Source: `reference/src/research-prompt.md`; read only the § ranges named here (§1 L5, §2 L23, §3 L43, §4 L79, §5 L98, §6 L132, §7 L191, §8 L224, §9 L260, §10 L286, §11 L300, §12 L333, §13 L350, §14 L362, §15 L376, §16 L399). Its Dhan text is superseded by D01.

## Scope
Index-only research on NIFTY 50 (1m), **paper only, never real orders**. Question: do distance-from-anchor and EMA-gap momentum features give a measurable edge for fixed-risk index trades? "Edge not established" is a valid result (D18). Labels `experimental|watch|paper`.
Non-goals: reversal claims, filter stacking, price-ending myths, naked option selling instructions, auto-merging Pine strategies, an ML platform, real-order execution.

## Reference config (1m chart; mode `conservative`, explicit `cost_pts`)
Targets 10 and 20 pts as SEPARATE experiments · stop 12 pts (experiments 10–15) · max hold 10 min · entries 09:30–14:45 IST · flatten at the session cutoff · one position at a time · no breakeven, partials, pyramiding, trailing.

## Features (causal; finalized bars only)
`P`=close, `F`=EMA9, `S`=EMA21 (seed documented; warm from prior history), `V`=anchor, `A`=the prior completed bar's ATR (valid and >0).
- `atr_sess`: Wilder ATR14 on the session-adjusted TR (first session bar TR = high−low). Distinct from standard ATR.
- Anchor `V`: session HLC3 VWAP when same-instrument volume is usable, else TWAP labelled "TWAP / equal-bar session average" (index spot ⇒ TWAP). Futures-volume-weighted spot ⇒ label `proxy weighted`.
- `D=(P−V)/A`, `E=(P−F)/A`, `M=(F−S)/A`; `price_to_slow=E+M`; `fast_to_anchor=D−E`; `slow_to_anchor=D−E−M`. Keep raw points beside normalised values.
- Rates over k=3 completed bars (ATR per bar; never bridge the session-anchor reset): `anchor_rate=((P−V)[t]−(P−V)[t−k])/(k·A)`, `gap_rate=((F−S)[t]−(F−S)[t−k])/(k·A)`. Zero/invalid `A` ⇒ NaN, never infinity. Different from NVS `devAtr[t]−devAtr[t−k]`.

## Baselines (named; no extra filters; a new condition = a new named variant)
- `anchor_cross_ema_order`: close crosses the anchor on a completed bar (prev close ≤ prev `V` and close > `V` for bull; mirrored for bear) with EMA order (`F>S` bull, `F<S` bear). **The prompt does not define this crossover; this is our interpretation. Log it in STATE Open issues and in the report.**
- `ema_gap_reexpansion`: bull = `gap_rate>0` and prior `gap_rate ≤ 0` and close > `F`; bear mirrored.
- `ema_aligned_gap_reexpansion`: the same plus `F>S` (bull) or `F<S` (bear).
The prompt's exploratory results table (109/451/286 trades etc.) is not reproducible (harness absent); it is not a target.

## Armed-resumption (setup → armed → entry → exit)
Write a short exact spec first in `docs/engines/research-armed.md` (formation, direction, trigger level, invalidation, timeout, cancellation, rearming); ASK the user only for genuine product choices. Rules: invalidation, expiry and one-shot rearm are frozen at arming · completed-close and intrabar triggers are separate modes (intrabar only with lower-TF/tick evidence) · skip setups that cannot respect the risk budget · never widen a stop · an opposite-colour candle is not invalidation.

## Outcomes (§8)
`TARGET_FIRST | STOP_FIRST | TIME_EXIT` (time exit = actual directional return). Ambiguous bars and data/session interruptions are tracked separately and never dropped from denominators. OHLC-only same-bar both-hit ⇒ `STOP_FIRST` + `ambiguous_bar` (optionally report bounds). Barriers are checked intrabar; no retrospective tightening; record the containing bar for intrabar exits.
Metrics: MAE, MFE, time-to-target/stop, first-minute adverse move, holding time, drawdown, each with its definition and path-resolution limits.

## Statistics and verdict (§9; thresholds are our choice, log them)
- Chronological split: development 50 % / validation 25 % / untouched evaluation 25 % by session, purge ≥ max-hold across boundaries; fit transforms/thresholds only on allowed data; record every tested variant.
- Per variant and experiment: trades, outcome mix incl. ambiguous/interrupted, net expectancy (pts, after `cost_pts`) with a session-clustered bootstrap 95 % interval (fixed seed); overlapping minute labels are not independent trades. No invented probabilities; no model in this chunk (calibrated model deferred).
- Verdict `edge_not_established` unless, on the untouched evaluation split, the interval's lower bound is > 0, the sign agrees on validation, and it survives leave-one-session-out. With < 60 sessions the report says "insufficient sessions" and the verdict cannot exceed `inconclusive`. A minimum sample count is not proof.

## Index vs option (§10)
Index research is in index points. Option P&L only with an explicit contract policy and recorded quotes (buy at ask, sell at bid evidence; never LTP/mid or reconstructed prices); `pts/prem/inr` never mixed (`UnitMismatch` test). An index-triggered paper option exit is synthetic (`synthetic=true`).

## Persistence, events, API (§11)
Durable concepts per §11. Idempotency key unique on `(engine_id, config_hash, instrument_id, signal_bar_start, side)`; checkpoint/cursor recovery; worker failures surface (never an empty success). Events use the shared envelope (D05) with types `research.watch|armed|entry|exit|invalidated`.

## Frontend (§12)
Index chart plus CE/PE charts when a contract policy exists; EMA9, EMA21 and anchor lines; diagnostics panel (D, E, M, rates, A, anchor kind); markers watch/armed/entry/exit/target/stop/invalidation; label `BEARISH INDEX / PUT CANDIDATE` (and bullish mirror); provisional shown separately; reconnect snapshot-first; never claim "three independent confirmations".

## Tests and ops (§13, §15)
batch == incremental == restart; future-bar immunity; session boundaries; zero-range bars; duplicates/out-of-order bars; timing, ambiguity and timeout-bar counting; 100k-bar replay measured and reported without blocking the request loop. Ops: localhost bind, token expiry, reconnect backoff, rate limits, instrument refresh, duplicate/delayed packets, clock skew, laptop sleep.
