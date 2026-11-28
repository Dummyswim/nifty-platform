# Market context panel (fair premium · India VIX · one-sided writing) — design

Branch `feature/premium-vix-writing` (worktree `nifty-platform-dev`, DB `nifty_dev`, ports 8001/8081), cut
from `main` at 58521c0. Built **before** the Sensex work; merge to `main` only after the user has tested it
on 8081 and says so.

## Intent
The user scalps the index and takes intraday directional option trades. A reel by *Dropout Trader*
(27 Nov 2026; user-supplied translation in the conversation) states a three-part rule:

> When **(1)** the option premium trades at fair value, **(2)** India VIX is high, and **(3)** writing builds
> on one side (call writing = bearish, put writing = bullish), the market moves in that direction.
> "Today call writing came in, so the market kept falling" (≈ −277 pts); "I saw it on the third candle";
> fair premium from *daily move ≈ Nifty × VIX ÷ √252*; "today the premium was cheap" (audio only, uncertain).

Read as an **option buyer's checklist**: writers (the funded side) give the direction, high VIX gives room
to move, fair-or-cheap premium means the buyer is not overpaying (no IV crush). The user wants a small box
on the chart that shows the three conditions and the resulting direction, live and on past days, so the
claim can be checked against recorded sessions rather than taken on trust.

## Goals
- A small panel on NIFTY index chart panes: VIX rank, premium verdict per side (CE / PE), writing score,
  resulting bias, and expected-move context. Live (refreshes ~15 s) and History/Replay (state at cursor).
- Deterministic per-minute state, recomputed from stored data, so any recorded day can be replayed.
- India VIX recorded live and one year of history stored.

## Non-goals
- Trade entries, stops, targets, sizing, alerts, backtests or research scoring of the bias (a later piece;
  this design only makes the per-minute series available for it).
- SENSEX (comes with the Sensex work: the endpoint takes `underlying`, only NIFTY is accepted now;
  SENSEX will use India VIX labelled `proxy`).
- Historical option OI before our recording began (Kite does not serve expired contracts).

## Anti-goals
- A bias shown on stale or missing inputs. Every missing input yields `n/a` with the reason (no rate set,
  VIX history short, no OI recorded, ticks older than `options.max_stale_s`).
- Lookahead: the state for minute *m* uses only data with timestamps ≤ end of *m*.
- Flicker: a bias that toggles minute to minute.
- Any NIFTY behaviour change elsewhere (charts, engines, options page, collector recording).
- Order placement of any kind.

## Constraints
- No new dependencies. Facts (expiries, strikes, lot, tick) from the Kite master; probabilities never invented.
- IV is computed with our Black–Scholes (`nifty.options.bs`, calendar-time `years_to_expiry`, q = 0) and
  needs the user's rate pref `options.r`; without it every IV-based field is `n/a ("set rate in Settings")`.
- Units suffixes as everywhere (`_pts`, `_prem`, vol in **vol points**, e.g. 14.2 = 14.2 %).
- Recorded window: the collector records ATM ± `options.window_steps` (default 5) for the expiry kinds in
  `options.record_kinds` (default: current weekly, next weekly, monthly). The writing strikes (N ≤ window)
  and the expiry-day switch to next weekly rely on that.

## Approaches (user picked A)
- **A. Recompute from stored data on request (chosen).** Pure module turns one day's stored inputs into a
  per-minute series; an endpoint serves it with a per-minute cache; the web panel polls in Live and reads
  the series at the cursor in History/Replay. No new tables; past days replay for free; hysteresis and
  confirmation are deterministic because they are always run over the whole day from the open.
- B. Collector computes live and stores a row per minute: fresher push, but a new table, logic split
  between collector and replay, and no panel for days the collector missed.
- C. Chart engine: engines see only index bars; would need option chain + VIX in the engine framework. Dropped.
- D. Browser-only: no replay/research, duplicates IV maths in TypeScript. Dropped.

## Data
1. **India VIX live**: the collector adds `kite:NSE:INDIA VIX` as a feed (1m bars, no engines), included in
   the (re)connect gap backfill and the EOD reconcile, like the NIFTY index. Missing from the master → logged,
   collector continues without it.
2. **India VIX history**: `kite-backfill --symbol "INDIA VIX"` for the 365 calendar days before today
   (existing job/CLI). Daily close = last 1m close of each session.
3. **Spot**: NIFTY 50 1m closes (existing). Previous session close for the day-move.
4. **Option premium per minute**: the option contracts' 1m bars (the collector already builds them from ticks).
5. **Option OI per minute**: last recorded OI in each minute from `ticks` (`db.options.oi_series` logic).
   **Baseline OI** for a contract = last OI recorded in the previous session; if none, its first OI today
   and the panel notes `writing since first tick`.

## Logic (pure module `nifty.context`, all thresholds are params with these defaults)
Evaluated for each closed 1m bar *m* of the session.

**Expiry used.** Nearest listed weekly expiry; on the expiry date itself use the next weekly
(flag `expiry_day: next weekly`).

**1. VIX high.** `vix_rank` = percentile rank of the latest VIX 1m close against the previous **252**
session closes (today excluded). `vix_high` when rank ≥ **70**. Fewer than 200 prior closes → `n/a`.

**2. Premium verdict, per side (CE and PE).**
- Side IV at the money = linear interpolation in strike between the two recorded strikes that bracket spot
  (IV of each from that minute's option close, spot, `options.r`, expiry).
- Reference = VIX (vol points). Band half-width `b = max(10 % × VIX, 1.0 vol pt)`.
  `FAIR` if |IV − VIX| ≤ b, `CHEAP` if IV < VIX − b, `RICH` if IV > VIX + b.
- Hysteresis: once in a state, leave it only when outside the exit band `max(13 % × VIX, 1.3)`.
- Context shown, not deciding (Claude's call): the side's **own recent IV** (median of its ATM IV over the
  previous 5 recorded sessions, same expiry kind; `n/a` under 3 sessions) and **realised vol** (NIFTY 1m
  log returns, previous 20 sessions, annualised, vol points). Notes: `IV rich vs own 5-day` when IV is
  above own recent + b; `IV < RV` when IV is below realised vol.
- Points view: straddle = CE + PE close at the ATM strike; fair straddle ≈ 0.8 × S × VIX/100 × √T
  (T = `years_to_expiry`); shown as `Straddle 231 / fair 240`.

**3. Writing.** Strikes: ATM ± **3** steps (re-chosen each minute from that minute's spot), the expiry above.
For each contract: ΔOI = OI(m) − baseline, Δprem = close(m) − baseline close (previous session's last close,
same fallback). It counts as **writing** only when ΔOI > 0 and Δprem < 0 (short build-up; OI up with
premium up is buying and counts 0).
- `CW` = Σ call writing, `PW` = Σ put writing. Day score `w_day = (PW − CW)/(PW + CW)` in [−1, 1]
  (0 when both 0). Negative = call writing = bearish.
- Rolling score `w_roll`: same formula on deltas over the last **15** minutes (baseline = values at m − 15).
- `one_sided` when |w_day| ≥ **0.3** and `w_roll` has the same sign (or is 0).
- Also shown, as in the reel: raw ΔOI calls vs puts (`ΣΔOI CE : ΣΔOI PE`), no price filter.

**Bias.**
- Candidate `BEARISH` when VIX high ∧ writing one-sided negative ∧ PE verdict ∈ {FAIR, CHEAP};
  `BULLISH` when VIX high ∧ one-sided positive ∧ CE verdict ∈ {FAIR, CHEAP}; else `NONE`.
- Shown only after the candidate holds for **3** consecutive closed minutes and not before **09:30 IST**
  (the reel's "third candle" on 5m).
- Once shown it persists until the candidate breaks for **2** consecutive minutes (writing |w_day| < 0.15
  or opposite, VIX rank < 65, or the buy side turns RICH beyond the exit band).
- Text: `BEARISH · buy PE ok` / `BULLISH · buy CE ok` / `NO BIAS` plus `since 10:12`.

**Expected move.** `exp_move_pts = S_prev_close × VIX_open/100 / √252`; `day_move_pts = S − S_prev_close`;
`used = |day_move| / exp_move` (e.g. `−180 / ±246 · 73 %`). Context only.

Params live under prefs key `context` (`band_pct 10, band_floor 1.0, exit_pct 13, vix_pct 70, vix_exit_pct 65,
strikes 3, w_min 0.3, w_exit 0.15, roll_min 15, confirm 3, release 2, not_before "09:30"`), editable later;
no UI for them in this piece (Claude's call).

## API
`GET /api/v1/context?underlying=NIFTY&date=YYYY-MM-DD` (auth like other routes; date default = today's/last
session; unknown underlying → 404, SENSEX → 404 until the Sensex work) →
`{underlying, date, expiry, params, series: [State], notes: [str]}`. `State` per closed minute:
`t, vix, vix_rank, vix_high, ce{iv, verdict, own_iv, note}, pe{…}, rv, straddle_prem, fair_straddle_prem,
w_day, w_roll, oi_ce, oi_pe, one_sided, candidate, bias, bias_since, exp_move_pts, day_move_pts, na_reason`.
Cached per (underlying, date, last closed minute); a past date is cached until restart.
Typed in `web/src/api/schemas.ts` via `make api-types`.

## Web
A compact box in the top-right of a NIFTY **index** pane (option panes: none), toggled as
"Market context" in the indicator list, **on by default**. Live: polls every 15 s, shows the last state.
History/Replay: shows the series entry at the replay cursor (≤ cursor, no lookahead).

```
┌ Market context ─────────── 10:47 ┐
│ VIX 18.4  P78  HIGH            ✓ │
│ CE IV 21.0 RICH · PE IV 17.6 FAIR│
│ Straddle 231 / fair 240          │
│ Writing CALL  −0.46 (15m −0.52)  │
│ ▼ BEARISH · buy PE ok  since 10:12│
│ Move −180 / ±246 · 73 %          │
└──────────────────────────────────┘
```
`n/a` rows show the reason in one line (e.g. `IV n/a: set rate in Settings`).

## Calls made by Claude (user may override)
- Verdict decided against VIX; own recent IV and realised vol are context notes, not gates.
- Writing strikes ATM ± 3; one-sided at |score| ≥ 0.3 with the 15-minute score agreeing; release at 0.15.
- Confirmation 3 minutes, release 2 minutes, nothing before 09:30.
- Panel on by default on index panes; thresholds editable only via the `context` pref for now.
- Expiry day uses next weekly for both premium and writing.
- A strike with no 1m bar in a minute (no trade) carries its last close/OI forward for up to
  `options.max_stale_s`; beyond that the strike is left out of writing, and an IV needing it is `n/a`.
- Writing strikes = min(3, `options.window_steps`), so a narrower recording window never asks for
  contracts that were not recorded.

## Left to the builder
- Module/function layout inside `nifty.context`; SQL shape of the day loader; cache implementation.
- Tests: VIX rank (252-window, today excluded, short history → n/a), band + floor + hysteresis, strike
  interpolation and ATM switch without jumps, writing classification (OI↑ prem↑ = 0), baseline fallback,
  confirmation/release, 09:30 gate, expiry-day switch, lookahead (state at m unchanged when later data is
  added), stale/missing inputs → `n/a`. API test on seeded ticks/bars; web vitest for cursor selection;
  e2e: panel visible with a bias on a seeded day. `make check`, `make e2e` green; NIFTY e2e unchanged.
- Manual on 8081 by the user: a live session (collector on dev during market hours only if the user
  chooses) and two or three recorded past days in Replay.

## Addendum (2026-11-27, after testing on copied main-DB data): two writing rules, two boxes
**Why:** on the recorded days (Nov 26 up, Nov 27 down) the original rule "OI↑ ∧ premium↓ vs the baseline"
pinned the writing score at +1.0 / −1.0 all day: on a down day every call loses premium and every put gains,
so put writing can never count. The score restated the day's direction. Dropped.

**Rules (user decision: both, side by side):**
- **`iv` — OI + IV:** a leg counts as writing when ΔOI > 0 and its IV did not rise vs the same baseline
  (day: IV at the previous session's last close, else first IV today; rolling: IV at m − `roll_min`).
  IV per leg from our Black–Scholes with that minute's spot; memoised per (contract, minute, price, spot).
  Score = (PW − CW)/(PW + CW) as before.
- **`oi` — raw OI (the reel's method):** ΔOI summed per side with no filter;
  score = (ΔOI_PE − ΔOI_CE) / (|ΔOI_PE| + |ΔOI_CE|), 0 when both are 0. Rolling the same over `roll_min`.
- Everything else (VIX, premium verdicts, confirmation/release, 09:30 gate, n/a rules) is shared.

**API:** `GET /context?…&writing=iv|oi` (default `iv`); response carries `writing`; cache key includes it.
Params: prefs `context` shared, plus optional per-rule overrides `context.iv` / `context.oi` (merged on top).
Default `w_min` / `w_exit` per rule are set from a calibration over the recorded days, confirmed by the user.

**Web:** two boxes stacked top-right on NIFTY index panes, titled `Writing: OI + IV` and `Writing: raw OI (reel)`,
each with its own sidebar switch (prefs `context.show_iv`, `context.show_oi`, default on; old `context.show`
is no longer read).

**Data note:** main collector recorded no option ticks 2026-11-26 09:36–11:12 IST; the panel shows n/a there.
