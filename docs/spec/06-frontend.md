# Frontend (`web/`; D26 React + TypeScript on Vite SPA, TanStack Query, Zustand)

API types come from OpenAPI (`make api-types`); never hand-write them.

## Pages
Chart (default: NIFTY 50, 1m) · Options · Backtests (+ audit) · Analytics · Research · Settings (Kite status + Connect, prefs, calendar/data).

## Chart (Lightweight Charts, D13)
- Candlesticks; TFs 1/3/5/10/15/30m, 1h, 1D (webapp L116–152); zoom, pan, crosshair, last-price marker, buy/sell markers.
- Drawing MVP: trendline, horizontal line, rectangle, text; stored per instrument in `drawings`; selection, move, delete.
- Indicator panel: toggle switches; param forms auto-generated from each engine's JSON Schema (`ui` params such as colours kept separate); persisted in `prefs`.
- Overlays: a renderer for every OverlayElement kind (zone, band, line, step_line, hline, marker, label, region) as custom series primitives (read the installed API in `web/node_modules/lightweight-charts/dist/typings.d.ts` first). Role tokens → theme colours. `plots` render as line/histogram series (overlay or own pane).
- Replay: cursor-driven; reveals bars, plots, events and overlay versions with `avail_at_utc <= cursor`; play/pause/step/speed; jump from an audit row.
- Live: WS snapshot-first; provisional bars/events drawn distinctly; reconnect with cursor; banner for connection and Kite status (`AUTH_EXPIRED` ⇒ "Connect Kite").

## Backtests, audit, analytics
Tables with sorting and filters; audit row opens the chart at the trade with entry/stop/target/exit lines; equity and drawdown (ECharts); export buttons (CSV/Excel/JSON).

## Options and Research
Options: C12 (`docs/spec/05-backend.md`; webapp L153–194). Research: C13 engine, C14 runs/statistics/UI (`docs/spec/07-research.md`).

## Engine panel
`panel()` rows `{label, value, role}` render as a small card for the selected engine. It shows the **latest** bar of the run (live: latest finalized/provisional via WS `panel`); it is not replayed (say so in the card when the replay cursor is not at the end).

## Tests
vitest for pure logic (resample cursor, overlay version picking, param-form mapping); Playwright smoke (`make e2e`): load Chart, switch TF, toggle an indicator, open an audit row. No image-snapshot tests.
