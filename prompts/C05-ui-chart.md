# C05 · UI chart core
effort: low · deps: C01 (C04 helpful) · reads: `docs/spec/06-frontend.md` (Pages, Chart, Tests) · `docs/spec/01-contracts.md` (Bar) · `docs/TOOLS.md` §3 · webapp prompt L114–152 (view_range)
pine: — · tools: browser canvas (DOM assertions → console errors → one screenshot ≤1280×800) · `grep` in `web/node_modules/lightweight-charts/dist/typings.d.ts` · bash (`npm`, `make e2e`) · create/edit

**Goal.** A TradingView-like candlestick chart on stored data: timeframes, crosshair, drawings, login. No indicators yet.

**Do**
1. Backend: `instruments`; `bars?symbol&tf&from&to&limit&cursor` (columnar `{t,o,h,l,c,v,flags}`, default limit 5000, time cursor; higher TFs through `marketdata.resample`; note the on-the-fly resample cost in STATE); `prefs` GET/PUT; `drawings` CRUD per instrument (one Alembic revision). All behind `require_user`; then `make api-types`.
2. `web/src/chart/ChartView`: candlesticks, volume pane only when `volume_kind != absent`, crosshair + OHLC legend, last-price marker, TF selector 1/3/5/10/15/30m, 1h, 1D, IST axis, older-bar loading by cursor. On load: NIFTY 50 at 1m (success criterion), last symbol/TF restored from `prefs`.
3. Drawing MVP (trendline, horizontal line, rectangle, text) as custom series primitives (read the installed typings first): select, move, delete; persisted through `drawings`. Keep hit-testing and coordinate maths in pure functions with vitest tests.
4. Pages: Login (polished), Chart, Settings shell (prefs; Kite status placeholder for C07). Lazy-load heavy chart code.
5. `make e2e` (Playwright smoke) via `tools/e2e_run.py`: create/seed `nifty_test` with the oracle CSV, start uvicorn and the built SPA on spare ports with a temporary password hash, run Playwright (login, chart loads bars, TF switch, a horizontal line survives reload), stop everything. `npx playwright install chromium` once (ASK if the download is a problem).

**Acceptance.** `make check` and `make e2e` green. In the browser canvas on the built app: DOM shows the candles and TF buttons, no console errors, one screenshot ≤1280×800 for me.
**Record in STATE:** routes, `ChartView` props, drawing storage shape, e2e harness usage.
