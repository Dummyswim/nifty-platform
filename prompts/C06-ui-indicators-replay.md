# C06 · UI indicators, overlays, replay, backtest pages (MVP)
effort: med · deps: C04, C05 · reads: `docs/spec/06-frontend.md` (all) · `docs/spec/01-contracts.md` (OverlayElement, EngineEvent, panel) · `docs/spec/05-backend.md` (API) · webapp prompt L195–231 and L246–283 (view_range)
pine: — · tools: browser canvas (DOM assertions → console errors → one screenshot ≤1280×800) · `grep` in `web/node_modules/lightweight-charts/dist/typings.d.ts` · bash (`npm`, `make e2e`) · create/edit
**If short:** 1 indicators + overlays · 2 replay · 3 Backtests/Audit/Analytics pages · 4 e2e + tag.

**Goal.** Engines on the chart (NVS on by default), replay, and the backtest, audit and analytics pages.

**Do**
1. **Indicator panel.** List `engines` (ready only). Toggle plus a param form generated from the JSON Schema (number/int with min/max, bool, enum; `x-ui` fields become the engine's `ui` block; any other type gets a raw-JSON field). Persist `indicators` in `prefs` as `{engine_id: {enabled, params, ui}}`. NVS is enabled by default (success criterion "VWAP strategy overlays automatically"). Enabling or changing params submits `engines/{id}/run` on the engine's `default_timeframe` (same key ⇒ cached), polls the job, shows running/failed (job error text), then loads plots/overlays/events. `ui`-only changes never rerun. Outputs are time-anchored, so they also draw on the 1m default chart.
2. **`web/src/overlay/pick.ts`** (pure, vitest): the latest `ver` per `id` with `avail_at_utc <= cursor`, `deleted` dropped, `t1=null` ⇒ extends to the cursor. Tests: supersession, deletion, future versions hidden, `t1=null`, role → colour.
3. **Renderers.** One custom series primitive per OverlayElement kind (`line step_line hline band zone marker label region`); role tokens → theme colours; zone `meta.status` styles active / mitigated / projected (dashed). `plots` as line/step/hist/area series, overlay or own pane per `PlotSpec.pane`. Entry/exit markers plus stop/target lines from events and trades. Lazy-load the chart bundle.
4. **Engine panel card** (spec/06): rows from `engine_runs.panel`; show "latest bar only" when the cursor is not at the end.
5. **Replay** (`web/src/replay/`, pure logic + tests): zustand `cursor` (UTC), play/pause, step ±1 bar, speed 1×/5×/20×/100×, jump to a time. Reveal bars, plots, events and overlay versions by `avail_at_utc` / `available_at_utc <= cursor`; never recompute. A "REPLAY" badge shows while the cursor is not at the end.
6. **Backtests page.** New-run form (engine + schema params, timeframe, range or snapshot, mode, qty, `cost_pts`) → job → progress. List; detail with metric cards (show `n_sessions`, `low_n`, and "n/a (no losses)" for a null profit factor), trades table (sort; filter by side/reason/result) and export buttons.
7. **Audit.** A row opens a drawer with the C04 audit payload. "Open on chart" navigates to Chart at the trade with entry/stop/target/exit lines; "Replay from here" sets the cursor.
8. **Analytics page** (ECharts, lazy-loaded): equity curve, drawdown, per-session P&L histogram, metric cards.
9. Extend `tools/e2e_run.py` to start the worker (against `nifty_test`) and add to the smoke: toggle an indicator, markers present, open an audit row.

**Acceptance.** `make check` and `make e2e` green. In the browser canvas on the oracle dataset: NVS markers present (15 entries), replay stepping reveals bars one at a time and hides future markers, an audit row opens the chart at its trade, no console errors; one screenshot for me. Then `git tag mvp-nvs`.
**Record in STATE:** prefs keys, overlay and replay module paths, routes, any API gaps found.
