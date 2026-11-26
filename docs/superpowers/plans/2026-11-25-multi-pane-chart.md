# Multi-pane Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 1 / 2 / 3 resizable chart panes in the Chart page, each on any index or recorded option contract, with indicators on every pane.

**Architecture:** Today's chart body becomes a `ChartPane` (own symbol/tf, indicators, live stream). A pure
`layout.ts` model holds layout/panes/active/sizes and its pref (de)serialisation; the store holds one
`ChartLayout`. One toolbar acts on the active pane; the active pane portals its Indicators sidebar and
engine cards into fixed slots. A small backend fix makes engine-run jobs re-run when new bars exist.

**Tech Stack:** React 19 + zustand + TanStack Query + lightweight-charts 5 (web), FastAPI + SQLAlchemy (backend), vitest, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-25-multi-pane-chart-design.md`

## Global Constraints
- Work only in the worktree `nifty-platform-dev` on `feature/sensex-multiview`; DB `nifty_dev`; dev ports 8001/8081 (`make start-dev`). Never touch `../nifty-platform`.
- No new dependencies (web or Python).
- Layouts exactly: `1` (default), `2` = `[A|B]`, `3` = A big left, B over C on the right.
- Pane min size 15 % (fraction clamp `0.15..0.85`); double-click a divider resets to `0.5`.
- Single-pane layout must behave exactly as today: existing `make e2e` smoke stays green unchanged.
- No change to engine/indicator computation or stored data. Option panes show recorded data only.
- Pref keys: new `chart_layout`; `chart` (`{symbol, tf}`) keeps being written for pane A.
- `make check` green after every task; commits use the repo's attribution trailer.

## Review Focus
1. Pane on an option contract with zero recorded bars → empty chart with "not recorded" note, no error toast, indicators show their normal status (no crash). → Task 7 vitest `paneNote`.
2. Saved `chart_layout` pref that is malformed or from an older shape (missing `sizes`, 3 panes but layout 1, unknown tf) → falls back to sane defaults, never a blank page. → Task 2 `fromPrefs` tests.
3. Panes with different timeframes (1m and 5m) under crosshair sync → the 5m pane shows the bucket containing the 1m time, not nothing. → Task 6 `bucketTime` tests.
4. Same symbol+tf+params resubmitted after new bars arrive → new engine run (not the stale cached one); with no new bars → cached run. → Task 1 tests.
5. "Open on chart" from Backtests/Research while layout is 3 and pane C is active → pane C switches to that symbol/tf and focuses, other panes untouched. → Task 3 `openOnChart` test.

---

### Task 1: Engine runs re-run when the symbol has newer bars

**Files:**
- Modify: `backend/src/nifty/api/routes.py:219-228`
- Modify: `backend/src/nifty/db/bars.py` (add helper)
- Test: `backend/tests/test_backtest_api.py`

**Interfaces:**
- Produces: `latest_bar_start(conn: Connection, instrument_id: str) -> datetime | None` in `nifty/db/bars.py`; engine-run payload gains `"data_until": <iso str | None>` when submitted by `symbol` (not `snapshot_id`). Handler ignores the key.

- [ ] **Step 1: Write failing test** `test_engine_run_reruns_after_new_bars` in `tests/test_backtest_api.py` (use the existing `api` fixture + oracle import flow from `test_api_job_flow`): POST `/api/v1/engines/pine.nvs_scalper/run` `{"symbol": SYMBOL}` twice → same `job_id`; `upsert_bars` one extra 1m bar after the last oracle bar (next valid session minute) → POST again → different `job_id`, `created` true.
- [ ] **Step 2:** `make test T=backend/tests/test_backtest_api.py` → FAIL (same job id after new bar).
- [ ] **Step 3:** Implement `latest_bar_start` (`SELECT max(bar_start_utc) FROM bars WHERE instrument_id=:i`); in the route, when `body.symbol` and no `body.snapshot_id`, resolve the instrument with `find_instrument` (404 if unknown is NOT added here: keep today's behaviour, the worker reports it) and set `payload["data_until"]`.
- [ ] **Step 4:** same test → PASS; `make check` green.
- [ ] **Step 5:** commit `Engine runs re-run when the symbol has newer bars`.

### Task 2: Pure layout model

**Files:**
- Create: `web/src/chart/layout.ts`
- Test: `web/src/chart/layout.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type LayoutN = 1 | 2 | 3;
  export interface PaneState { symbol: string; tf: Tf; kind: "index" | "option"; label?: string }
  export interface Sizes { col: number; row: number }  // col: left width fraction; row: B height fraction (layout 3)
  export interface ChartLayout { layout: LayoutN; active: number; panes: PaneState[]; sizes: Sizes }
  export const MIN_FRAC = 0.15;
  export function defaultLayout(symbol: string, tf: Tf): ChartLayout;          // 1 pane, sizes {0.5,0.5}
  export function setLayoutN(l: ChartLayout, n: LayoutN): ChartLayout;          // grow: copy active pane; shrink: keep first n, clamp active
  export function updatePane(l: ChartLayout, i: number, p: Partial<PaneState>): ChartLayout;
  export function clampFrac(f: number): number;                                 // MIN_FRAC..1-MIN_FRAC, NaN -> 0.5
  export function dragFrac(startFrac: number, deltaPx: number, totalPx: number): number; // clamped
  export function fromPrefs(chartLayout: unknown, chart: unknown, fallback: { symbol: string; tf: Tf }): ChartLayout;
  export function toPrefs(l: ChartLayout): { chart_layout: ChartLayout; chart: { symbol: string; tf: Tf } };
  ```
  `panes.length === layout` always holds after every function.
- [ ] **Step 1:** Tests: `defaultLayout` shape; `setLayoutN` 1→3 copies active pane twice, 3→2 keeps A,B and clamps `active` 2→1; `dragFrac(0.5, 100, 1000) === 0.6`, `dragFrac(0.5, -900, 1000) === 0.15`; `clampFrac(NaN) === 0.5`; `fromPrefs(undefined, {symbol:"X",tf:"5m"}, fb)` → 1 pane X/5m; `fromPrefs({layout:3, panes:[one]}, …)` → 3 panes padded; unknown tf → fallback tf; missing sizes → 0.5/0.5; `toPrefs` writes `chart` from pane 0.
- [ ] **Step 2:** `cd web && npx vitest run src/chart/layout.test.ts` → FAIL (module missing).
- [ ] **Step 3:** Implement `layout.ts` (pure, no React).
- [ ] **Step 4:** vitest PASS; `make check` green.
- [ ] **Step 5:** commit `Chart layout model`.

### Task 3: Store holds the layout; "Open on chart" targets the active pane

**Files:**
- Modify: `web/src/store.ts`, `web/src/backtests/AuditDrawer.tsx:27`, `web/src/research/Research.tsx:97`, `web/src/pages/Chart.tsx` (read active pane instead of `symbol`/`tf`; restore from prefs via `fromPrefs`; save via `toPrefs`)
- Test: `web/src/store.test.ts`

**Interfaces:**
- Consumes: Task 2.
- Produces: in `useUi`: `chart: ChartLayout`, `setChart(l: ChartLayout)`, and
  `openOnChart(o: { symbol?: string; tf: Tf; focus: Focus }): void` (sets page "chart", updates the active pane's symbol/tf, kind stays/becomes "index" when a symbol is given, sets `focus`). `symbol`/`tf` fields are removed from `Ui`.
- [ ] **Step 1:** Test `openOnChart` on a 3-pane layout with active 2: only pane 2 changes, page = "chart", focus set.
- [ ] **Step 2:** vitest → FAIL.
- [ ] **Step 3:** Implement; switch the two callers to `openOnChart`; Chart.tsx uses `chart.panes[chart.active]` for today's single view; saving prefs PUTs both `chart_layout` and `chart`.
- [ ] **Step 4:** `make check` green; `make e2e` green (single pane unchanged).
- [ ] **Step 5:** commit `Store keeps a chart layout; open-on-chart targets the active pane`.

### Task 4: Extract `ChartPane` (still one pane on screen)

**Files:**
- Create: `web/src/chart/ChartPane.tsx`
- Modify: `web/src/pages/Chart.tsx`, `web/src/styles.css`

**Interfaces:**
- Produces:
  ```ts
  export function ChartPane(props: {
    index: number; pane: PaneState; active: boolean; live: boolean; tool: Tool;
    onActivate: () => void; onToolDone: () => void;
    onTimes?: (t: number[]) => void;                 // only the active pane reports (replay bar)
    sidebarSlot: HTMLElement | null; cardsSlot: HTMLElement | null; bannerSlot: HTMLElement | null;
    syncTime?: number | null; onCrosshairTime?: (t: number | null) => void;  // wired in Task 6
  }): JSX.Element
  ```
  Owns: instruments lookup, drawings queries/mutations, `useIndicators`, `useLiveStream`, `ChartView`. When `active`, portals `IndicatorPanel` into `sidebarSlot`, `EnginePanel` cards into `cardsSlot`, live banner into `bannerSlot` (`createPortal`). Root `div.pane` with `data-testid="pane"`, `data-active`, `onPointerDownCapture={onActivate}`.
- Chart.tsx keeps: toolbar, mode, tool, layout state, slots (`div.ind-slot`, `div.cards`, `div.banner-slot`) — the slots sit where those elements are today so 1-pane DOM/visuals match.
- [ ] **Step 1:** Run `make e2e` before the change as the baseline (green).
- [ ] **Step 2:** Refactor (no behaviour change).
- [ ] **Step 3:** `make check` + `make e2e` green with the smoke spec untouched.
- [ ] **Step 4:** commit `Extract ChartPane`.

### Task 5: Split layout, dividers, layout switch

**Files:**
- Create: `web/src/chart/SplitLayout.tsx`
- Modify: `web/src/pages/Chart.tsx` (toolbar `seg` "Layout" with buttons `1 2 3`, `data-testid="layout-<n>"`), `web/src/styles.css`

**Interfaces:**
- Consumes: Task 2 `dragFrac`, `clampFrac`, `setLayoutN`; Task 4 `ChartPane`.
- Produces: `SplitLayout({ layout: LayoutN; sizes: Sizes; onSizes: (s: Sizes, done: boolean) => void; children: ReactNode[] })`. CSS grid: layout 2 → columns `col fr | 6px | 1-col fr`; layout 3 → A spans both rows, right column rows `row | 6px | 1-row`. Dividers `div.divider[data-testid="divider-col"|"divider-row"]` with pointer capture; `onSizes(…, false)` while dragging, `(…, true)` on release (Chart saves prefs only when `done`); double-click → 0.5. Active pane gets `.pane.active` (accent 1px outline).
- [ ] **Step 1:** Implement (divider maths already tested in Task 2).
- [ ] **Step 2:** `make start-dev`, log in on 8081, manually: switch 1→2→3→1, drag both dividers, charts redraw live (lightweight-charts `autoSize`), reload keeps layout.
- [ ] **Step 3:** `make check` green.
- [ ] **Step 4:** commit `Split layout with resizable panes`.

### Task 6: Crosshair time sync

**Files:**
- Modify: `web/src/chart/ChartView.tsx` (props `syncTime?: number | null`, `onCrosshairTime?: (t: number | null) => void`), `web/src/chart/geometry.ts` (helper), `web/src/pages/Chart.tsx` (hold `hoverTime`, pass to non-hovered panes)
- Test: `web/src/chart/geometry.test.ts`

**Interfaces:**
- Produces: `bucketTime(times: number[], t: number): number | null` in `geometry.ts` — the last bar start `<= t` in `times` (ascending), `null` if `t` precedes all or `times` empty.
- ChartView: report the hovered time from the existing `onMove` (only for user-originated moves: ignore while applying `syncTime`); apply `syncTime` via `chart.setCrosshairPosition(close, bucketTime(...), series)`, or `clearCrosshairPosition()` when null/no bucket.
- [ ] **Step 1:** Tests: `bucketTime([0,300,600], 450) === 300`; `(…, 600) === 600`; `(…, -1) === null`; `([], 5) === null`.
- [ ] **Step 2:** vitest → FAIL. **Step 3:** implement helper + wiring. **Step 4:** vitest PASS, `make check` green; manual: hover pane A, crosshair line appears at the same time in B/C, including a 5m pane.
- [ ] **Step 5:** commit `Crosshair follows time across panes`.

### Task 7: Option contracts in panes (picker, label, live indicator refresh)

**Files:**
- Create: `web/src/chart/OptionPicker.tsx`, `web/src/chart/optionPane.ts`
- Modify: `web/src/pages/Chart.tsx` (symbol select gets an `Option…` entry → opens picker for the active pane), `web/src/chart/ChartPane.tsx`, `web/src/indicators/useIndicators.ts` (optional 4th arg `refresh?: number` added to the run queryKey)
- Test: `web/src/chart/optionPane.test.ts`

**Interfaces:**
- Consumes: `GET /options/expiries?underlying=NIFTY` (`ExpiriesOut`), `GET /options/chain?expiry&underlying&width` (`ChainOut`: `atm`, `rows[{strike, atm, ce, pe}]`, side `{contract_id, recorded}`), Task 2 `updatePane`, Task 1 `data_until`.
- Produces in `optionPane.ts`:
  ```ts
  export function contractLabel(underlying: string, expiry: string, strike: number, type: "CE" | "PE"): string; // "NIFTY 26DEC 25800 CE"  (expiry ISO -> DDMON, upper)
  export function paneNote(kind: PaneState["kind"], bars: number): string | null; // option && bars===0 -> "not recorded"; else null
  ```
- Picker: expiry select (kinds labelled current weekly / next weekly / monthly when present) → strike list with the ATM row marked → CE / PE buttons; unrecorded sides show "not recorded" but stay selectable. Choosing sets the active pane `{symbol: contract_id, kind: "option", label}`.
- ChartPane, option kind: legend/title uses `label`; `paneNote` shown in the pane; live mode does NOT use the collector source — it calls `useIndicators(symbol, tf, null, finalized)` where `finalized` increments on each non-provisional `sub.bars` delivery (Task 1 makes the re-submit a new run when bars grew).
- [ ] **Step 1:** Tests: `contractLabel("NIFTY","2026-12-29",25800,"CE") === "NIFTY 29DEC 25800 CE"`; `paneNote("option",0) === "not recorded"`; `paneNote("option",5) === null`; `paneNote("index",0) === null`.
- [ ] **Step 2:** vitest → FAIL. **Step 3:** implement. **Step 4:** `make check` green.
- [ ] **Step 5:** commit `Option contracts in chart panes`.

### Task 8: End-to-end panes test, docs

**Files:**
- Create: `web/e2e/panes.spec.ts`
- Modify: `docs/STATE.md` (Interfaces: layout pref, `data_until`; Deviations: engine-run key now includes `data_until`; Open issues: none new), `docs/TODO.md` if anything new surfaced

- [ ] **Step 1:** Spec (same login helper pattern as `smoke.spec.ts`): click `layout-3` → 3 `pane` elements; activate pane 3, choose `Option…` → pick the first recorded contract from the `options_demo` fixture → pane 3 `chart` has `data-symbol` = that contract id and `data-bars` > 0; drag `divider-col` by +100 px → left pane width grows; reload → still 3 panes and pane 3 still on the contract; click `layout-1` → 1 pane.
- [ ] **Step 2:** `make e2e` → both specs green.
- [ ] **Step 3:** `make check` green; update STATE.md.
- [ ] **Step 4:** commit `Multi-pane chart: e2e and docs`.
- [ ] **Step 5:** Hand to the user: `make start-dev` → http://127.0.0.1:8081 to try. Merge to `main` only after the user says so.
