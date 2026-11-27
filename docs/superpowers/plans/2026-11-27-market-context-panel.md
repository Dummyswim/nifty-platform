# Market Context Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A small box on NIFTY index panes showing India VIX rank, fair/cheap/rich premium per side, one-sided writing and the resulting bias — live and at the replay cursor.

**Architecture:** A pure package `nifty.context` turns one session's stored inputs (VIX bars + prior daily closes, NIFTY 1m bars, option 1m bars and per-minute OI) into a per-minute `State` series. `GET /api/v1/context` loads the day, runs the series and caches it per closed minute. The web polls it in Live and picks the entry at the cursor in History/Replay. The collector additionally records `INDIA VIX`.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / pydantic / pytest; React 19 / TanStack Query / vitest / Playwright.

**Spec:** `docs/superpowers/specs/2026-11-27-market-context-panel-design.md`

## Global Constraints
- Worktree `nifty-platform-dev`, branch `feature/premium-vix-writing`, DB `nifty_dev`, ports 8001/8081; never touch `../nifty-platform`. Merge only after the user tests on 8081 and says so.
- No new dependencies. NIFTY behaviour elsewhere unchanged: existing pytest + `make e2e` pass without editing their assertions.
- No lookahead: state at minute m uses only data with timestamps ≤ end of m.
- Missing/stale input → `n/a` with a reason string, never a bias. IV needs pref `options.r`; absent → reason `"IV n/a: set rate in Settings"`.
- Vol in vol points (14.2 = 14.2 %). Unit suffixes `_pts`, `_prem`.
- Defaults (prefs key `context`, verbatim): `band_pct 10, band_floor 1.0, exit_pct 13, vix_pct 70, vix_exit_pct 65, strikes 3, w_min 0.3, w_exit 0.15, roll_min 15, confirm 3, release 2, not_before "09:30"`. VIX window 252 prior closes, min 200. Own-IV 5 sessions (min 3). RV 20 sessions. Fair straddle factor 0.8.
- `make check` green after every task; commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus
1. Replay of a day where the ATM strike changes mid-session → IV and writing don't jump on the switch minute. → Task 2 `test_interp_iv_continuous_across_atm_switch`, Task 4 `test_series_atm_switch_no_bias_flip`.
2. Collector restarted mid-day (gap in option ticks of several minutes) → strikes past `options.max_stale_s` drop out, bias becomes `n/a`/released, not frozen. → Task 4 `test_stale_strike_dropped`.
3. A day with no prior-session OI (first recorded day) → writing still computed from first tick, note `writing since first tick`. → Task 4 `test_baseline_fallback_first_tick`.
4. Expiry day → premium and writing use next weekly; if next weekly not recorded → `n/a` reason, no crash. → Task 4 `test_expiry_day_uses_next_weekly`, `test_expiry_day_next_weekly_missing`.
5. Request for today before 09:15 or a holiday → empty series with a note, 200 not 500. → Task 5 `test_context_no_session`.

---

### Task 1: Record India VIX

**Files:** Modify `backend/src/nifty/collector/kite_run.py` (`run`: VIX feed in `pipe`, `tokens`, the (re)connect backfill and EOD reconcile loops); Test `backend/tests/unit/collector/test_kite_run_vix.py` (create)

**Interfaces — Produces:** `VIX_SYMBOL = "INDIA VIX"`; `def vix_index(ins: list[Instrument]) -> Instrument | None` (INDEX, exchange NSE, tradingsymbol `INDIA VIX`, provider_token set; else None). In `run`: `extra = [i for i in (fut, vix) if i]` style list so backfill/reconcile loop over `(idx, fut, vix)`; VIX feed added with no engines; missing → `log.warning("INDIA VIX not in master; recording without it")`.

- [ ] Step 1: tests: `vix_index` returns the VIX row from a list holding NIFTY 50, INDIA VIX, a BSE index; returns None when absent; returns None when its `provider_token is None`.
- [ ] Step 2: `make test T=backend/tests/unit/collector/test_kite_run_vix.py` → FAIL (import error).
- [ ] Step 3: implement `vix_index` + wire into `run`.
- [ ] Step 4: PASS; `make check`; `make test T=backend/tests/test_live_pipeline.py` green.
- [ ] Step 5: commit `Collector records INDIA VIX`.

### Task 2: Volatility maths (`nifty.context.vol`) and params

**Files:** Create `backend/src/nifty/context/__init__.py`, `backend/src/nifty/context/params.py`, `backend/src/nifty/context/vol.py`; Test `backend/tests/unit/context/__init__.py`, `backend/tests/unit/context/test_vol.py`

**Interfaces — Produces:**
```python
class ContextParams(BaseModel):  # extra="forbid"; fields = Global Constraints defaults
    band_pct: float = 10; band_floor: float = 1.0; exit_pct: float = 13
    vix_pct: float = 70; vix_exit_pct: float = 65; strikes: int = 3
    w_min: float = 0.3; w_exit: float = 0.15; roll_min: int = 15
    confirm: int = 3; release: int = 2; not_before: str = "09:30"
Verdict = Literal["FAIR", "CHEAP", "RICH"]
def vix_rank(prior_closes: Sequence[float], vix: float) -> float | None      # % of prior <= vix, 0..100; None if len<200; uses last 252
def band(vix: float, pct: float, floor: float) -> float                       # max(pct/100*vix, floor)
def verdict(iv: float, vix: float, prev: Verdict | None, p: ContextParams) -> Verdict   # entry band, exit band when prev set
def interp_iv(spot: float, lo: tuple[float, float], hi: tuple[float, float]) -> float  # (strike, iv) pairs; linear in strike; lo==hi strike -> lo iv
def realised_vol(closes_1m_by_session: Sequence[Sequence[float]]) -> float | None      # log returns within sessions, sqrt(375*252)*std*100; None if <2 sessions
def fair_straddle_prem(spot: float, vix: float, t_years: float) -> float               # 0.8*spot*vix/100*sqrt(t)
def expected_move_pts(prev_close: float, vix_open: float) -> float                     # prev_close*vix_open/100/sqrt(252)
```
- [ ] Step 1: tests:
  - `vix_rank([10.0]*199, 12)` is None; `vix_rank(list(range(1, 301)), 280.5)` uses only last 252 (49..300) → `round(.., 1) == 92.1`.
  - `band(14, 10, 1.0) == 1.4`; `band(8, 10, 1.0) == 1.0`.
  - `verdict(15.3, 14, None, P) == "FAIR"`; `verdict(15.5, 14, None, P) == "RICH"`; `verdict(12.5, 14, None, P) == "CHEAP"`; hysteresis: `verdict(15.6, 14, "FAIR", P) == "FAIR"` (exit band 1.82), `verdict(15.9, 14, "FAIR", P) == "RICH"`.
  - `test_interp_iv_continuous_across_atm_switch`: `interp_iv(24999.9, (24950, 14.0), (25000, 15.0))` and `interp_iv(25000.1, (25000, 15.0), (25050, 16.0))` differ by < 0.01.
  - `fair_straddle_prem(26000, 15, 2/365)` ≈ 230.9 (abs 0.5); `expected_move_pts(26000, 15)` ≈ 245.7 (abs 0.1).
  - `ContextParams(foo=1)` raises.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: PASS + `make check`. Step 5: commit `Context: volatility maths`.

### Task 3: Writing classification (`nifty.context.writing`)

**Files:** Create `backend/src/nifty/context/writing.py`; Test `backend/tests/unit/context/test_writing.py`

**Interfaces — Produces:**
```python
@dataclass(frozen=True)
class Leg: is_call: bool; oi: float; prem: float; oi_base: float; prem_base: float
def writing_qty(leg: Leg) -> float            # dOI if dOI>0 and dPrem<0 else 0.0
def score(legs: Sequence[Leg]) -> float        # (PW-CW)/(PW+CW); 0.0 when both 0
def raw_oi(legs: Sequence[Leg]) -> tuple[float, float]   # (sum dOI calls, sum dOI puts), no price filter
def one_sided(w_day: float, w_roll: float, w_min: float) -> int   # -1/0/+1: |w_day|>=w_min and (w_roll==0 or same sign)
```
- [ ] Step 1: tests: OI +100 prem −5 → 100; OI +100 prem +5 → 0 (buying); OI −50 → 0; calls writing 300 / puts 100 → score −0.5; nothing → 0.0; `raw_oi` counts the OI↑prem↑ leg; `one_sided(-0.46, -0.52, .3) == -1`, `one_sided(-0.46, 0.2, .3) == 0`, `one_sided(-0.46, 0.0, .3) == -1`, `one_sided(0.29, 0.5, .3) == 0`.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: PASS + `make check`. Step 5: commit `Context: writing classification`.

### Task 4: Per-minute series (`nifty.context.series`)

**Files:** Create `backend/src/nifty/context/series.py`; Test `backend/tests/unit/context/test_series.py` (synthetic `DayInputs` built in the test file with a small factory)

**Interfaces:**
- Consumes: Task 2 and 3 functions; `nifty.options.bs.implied_vol`, `years_to_expiry`; `nifty.options.chain.atm`, `strike_step`.
- Produces:
```python
@dataclass(frozen=True)
class OptSeries: strike: float; is_call: bool; expiry: date
    close: dict[datetime, float]; oi: dict[datetime, float]   # keyed by 1m bar start UTC
    prev_close: float | None; prev_oi: float | None          # previous session's last values
@dataclass(frozen=True)
class DayInputs: day: date; minutes: list[datetime]          # session 1m bar starts (UTC), closed only
    spot: dict[datetime, float]; prev_spot_close: float | None
    vix: dict[datetime, float]; vix_prior_closes: list[float]
    own_iv: dict[tuple[str, bool], float]   # (expiry kind "weekly", is_call) -> median ATM IV of prior 5 sessions; missing key = n/a
    rv: float | None; r: float | None; max_stale_s: float
    expiries: list[date]                     # listed weekly expiries, sorted
    options: list[OptSeries]
class Side(TypedDict): iv: float | None; verdict: str | None; own_iv: float | None; note: str | None
class State(TypedDict):  # field names exactly as the spec's API State
    t: int; vix: float | None; vix_rank: float | None; vix_high: bool | None
    ce: Side; pe: Side; rv: float | None; straddle_prem: float | None; fair_straddle_prem: float | None
    w_day: float | None; w_roll: float | None; oi_ce: float | None; oi_pe: float | None
    one_sided: int | None; candidate: str; bias: str; bias_since: int | None
    exp_move_pts: float | None; day_move_pts: float | None; na_reason: str | None
def choose_expiry(day: date, expiries: Sequence[date]) -> date | None   # nearest >= day; if == day -> next one; None if missing
def build_series(inp: DayInputs, p: ContextParams) -> tuple[date | None, list[State], list[str]]   # (expiry used, series, notes)
```
`candidate`/`bias` ∈ `"BEARISH" | "BULLISH" | "NONE"`; `t` = bar start epoch s. Algorithm (not determined by signatures):
```
for each minute m in order (state carried: verdict per side, vix_high latch, bias, run counters):
  strikes in play = ATM(spot[m]) ± min(p.strikes, recorded window) for the chosen expiry
  a leg's close/oi at m = latest value at <= m within max_stale_s, else the leg is dropped
  vix_high latch: on at rank>=vix_pct, off at rank<vix_exit_pct
  candidate = BEARISH if vix_high and one_sided==-1 and pe.verdict in {FAIR,CHEAP}; BULLISH mirror on ce; else NONE
  local time < not_before -> bias stays NONE (counters still advance)
  bias switches to candidate after `confirm` consecutive minutes of the same non-NONE candidate;
  a shown bias is released after `release` consecutive minutes where it is no longer the candidate
  any na_reason at m -> candidate NONE for that minute
```
Notes: `"writing since first tick"` when any leg used a first-tick baseline; `"expiry day: next weekly"`.
- [ ] Step 1: tests (each builds a 40-minute synthetic day starting 09:15 IST, VIX 18 with 252 prior closes ranging 10–20, r=0.065, CE/PE priced from `bs()` at chosen IVs so IVs are known):
  - `test_bearish_after_confirm`: call writing from 09:16, PE IV = VIX → bias NONE at 09:31, `"BEARISH"` from the 3rd consecutive candidate minute ≥ 09:30, `bias_since` = that minute.
  - `test_no_bias_before_0930`: same inputs, every state with IST time < 09:30 has bias NONE.
  - `test_rich_put_blocks_bearish`: PE IV = VIX + 3 → candidate NONE.
  - `test_release_after_two`: writing flips to neutral at minute k → bias still BEARISH at k, NONE at k+1.
  - `test_series_atm_switch_no_bias_flip`: spot crosses a strike boundary mid-bias → bias unchanged.
  - `test_stale_strike_dropped`: legs silent for > max_stale_s → `w_day` from remaining legs; all silent → `na_reason` set, bias released after `release`.
  - `test_baseline_fallback_first_tick`: `prev_oi=None` → notes contain `"writing since first tick"`.
  - `test_expiry_day_uses_next_weekly` / `test_expiry_day_next_weekly_missing` (→ every state `na_reason` mentions expiry, no exception).
  - `test_rate_missing`: `r=None` → `ce.iv is None` and `na_reason == "IV n/a: set rate in Settings"`.
  - `test_short_vix_history`: 150 prior closes → `vix_rank is None`, bias NONE.
  - `test_no_lookahead`: series for inputs truncated at minute 25 equals the first 25 states of the full series.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: PASS + `make check`. Step 5: commit `Context: per-minute series and bias`.

### Task 5: Day loader + `GET /api/v1/context`

**Files:** Create `backend/src/nifty/db/context.py`, `backend/src/nifty/api/context_routes.py`; Modify `backend/src/nifty/api/main.py` (include router); Test `backend/tests/test_context_api.py`; regenerate `web/src/api/schemas.ts` (`make api-types`)

**Interfaces:**
- Consumes: Task 4 `DayInputs`, `build_series`; `db.options` helpers; prefs `options.r`, `options.max_stale_s` (default as in options routes), `options.window_steps`, `context`.
- Produces:
```python
def load_day(conn: Connection, underlying: str, day: date, now: datetime) -> DayInputs   # db/context.py; only closed minutes (bar end <= now)
def session_for(conn: Connection, cal: Calendar, day: date | None, now: datetime) -> date | None   # default: today if a session day with bars, else last session with NIFTY bars
```
Route: `GET /context?underlying=NIFTY&date=` → `ContextOut {underlying, date: date|None, expiry: date|None, params: dict, series: list[StateOut], notes: list[str]}` (pydantic mirrors of `State`). `underlying != "NIFTY"` → 404. Cache: `functools`-free dict keyed `(underlying, day, last closed minute)`, max 16 entries, cleared on params pref change (key includes `json.dumps(params, sort_keys=True)`). VIX instrument = `kite:NSE:INDIA VIX` (any provider with tradingsymbol `INDIA VIX` as fallback, like `spot`). Prior closes = last 1m close per session before `day` (SQL `DISTINCT ON (session date)`), newest 252. Own IV = median ATM IV per side of each of the previous 5 sessions computed with Task 2/4 helpers from those days' option bars (skip days without bars). RV from the previous 20 sessions of NIFTY 1m closes.
- [ ] Step 1: tests on `nifty_test` (marker `db`): seed NIFTY 50 1m bars for two sessions, INDIA VIX bars for 260 sessions (one close each) + the test day, CE/PE contracts ATM ± 3 for a weekly expiry with ticks carrying OI (calls writing), pref `options.r = 0.065`:
  - `test_context_bias_on_seeded_day`: 200, `series[-1]["bias"] == "BEARISH"`, `expiry` = seeded weekly, every `t` < now.
  - `test_context_without_rate`: delete pref → every `ce.iv` null, `na_reason` = `"IV n/a: set rate in Settings"`.
  - `test_context_no_session`: `date=` a holiday → 200, `series == []`, a note.
  - `test_context_unknown_underlying`: `SENSEX` → 404; no cookie → 401.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: PASS + `make check` + `make api-types`. Step 5: commit `Context API`.

### Task 6: Web panel

**Files:** Create `web/src/context/pick.ts`, `web/src/context/pick.test.ts`, `web/src/context/useMarketContext.ts`, `web/src/context/ContextBox.tsx`; Modify `web/src/chart/ChartPane.tsx` (render `ContextBox` absolutely positioned top-right inside the pane when the pane is a NIFTY index pane and pref `context.show !== false`), `web/src/indicators/IndicatorPanel.tsx` (checkbox "Market context" bound to pref `context.show`, default checked), CSS in the existing stylesheet; Test `web/e2e/smoke.spec.ts` (one added assertion block)

**Interfaces:**
- Consumes: `ContextOut` from `web/src/api/schemas.ts`.
- Produces:
```ts
export function pickState(series: StateOut[], cursor: number | null): StateOut | null  // cursor null -> last; else last with t <= cursor; none -> null
export function useMarketContext(underlying: string, live: boolean, date?: string): { data?: ContextOut; error?: unknown }  // refetchInterval 15_000 when live, else no polling
export function ContextBox(props: { data?: ContextOut; cursor: number | null }): JSX.Element   // data-testid="context-box", data-bias=<bias>
```
Box rows and copy exactly as the spec sketch (`VIX 18.4  P78  HIGH`, `CE IV 21.0 RICH · PE IV 17.6 FAIR`, `Straddle 231 / fair 240`, `Writing CALL −0.46 (15m −0.52)`, `▼ BEARISH · buy PE ok  since 10:12` / `▲ BULLISH · buy CE ok …` / `NO BIAS`, `Move −180 / ±246 · 73 %`); `na_reason` replaces the affected rows with one line; times in IST HH:MM.
- [ ] Step 1: vitest `pick.test.ts`: null cursor → last; cursor between two `t` → earlier; cursor before first → null; empty → null.
- [ ] Step 2: `cd web && npx vitest run src/context` → FAIL. Step 3: implement pick + hook + box + wiring.
- [ ] Step 4: vitest PASS. Step 5: e2e assertion in `smoke.spec.ts`: on the oracle chart `context-box` is visible and shows an `n/a` line (oracle has no option data); unchecking "Market context" hides it. `make e2e` + `make check` green (existing e2e assertions unedited). Step 6: commit `Market context panel`.

### Task 7: VIX history on dev DB, docs, hand-over

- [ ] Step 1 (`nifty_dev` only): `python -m nifty.cli kite-backfill --symbol "INDIA VIX" --from <today − 365 d> --to <today>`; `make db-q` count of distinct sessions ≥ 240. If the dev DB has no Kite token, copy the newest `kite_tokens` row from `nifty` (read-only there; never print it), as in the Sensex plan.
- [ ] Step 2: `GET /api/v1/context` on 8001 for the last recorded session returns a series (record the result, or the `n/a` reasons, in the hand-over).
- [ ] Step 3: Update `docs/STATE.md` Interfaces (`nifty.context`, `/context`, prefs `context`/`context.show`, collector VIX feed) and `docs/TODO.md` (research scoring of the bias; SENSEX via registry with VIX `proxy`; params UI). Commit `Market context: docs`.
- [ ] Step 4: hand to the user: `make start-dev` → 8081: panel on a NIFTY pane, Replay two or three recorded days, set `options.r` if missing; a live session only if they choose to run the dev collector.
