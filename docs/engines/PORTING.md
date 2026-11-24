# Porting another Pine script (checklist)

1. **Map**: write `docs/pine/<name>.md` (inputs, series, state, plots, alerts); Pine source wins over the map.
2. **Ranges**: read only the cited line ranges of the Pine file; list every `var`, `request.security`, `ta.*` call.
3. **Params**: `EngineParams` with the Pine defaults; chart-only knobs in a separate `ui` model (not in the config hash).
4. **Bar order**: engine = incremental `on_bar` on closed bars; signal at the close, fill at the next open (spec/03).
5. **Primitives**: reuse `pinekit` (ta.*, na handling, session/HTF context); add a primitive with its own test.
6. **State**: every field JSON-serialisable; `snapshot()`/`restore()`; no wall clock, no random, no network.
7. **Plots/overlays**: declare `PlotSpec`s; hide helper plots (role `hidden`); overlays keyed by stable ids.
8. **Debug plots**: add a debug Pine copy exporting internal series so TradingView can be compared bar by bar.
9. **Golden export**: export OHLC + plots from TradingView into `fixtures/tv_golden/<engine>/`; `make parity E=<id>`.
10. **Tests (tiers)**: unit per primitive/step, oracle counts, golden file, then D14 properties:
    batch == incremental == restart, and a prefix run equals the same prefix of the full run (no lookahead).
11. **Register**: add the module to `BUILTIN_ENGINE_MODULES`; keep `ready=False` until golden parity is
    recorded (or the gap is logged in STATE), then set `ready=True`.
12. **Engine id** stays unique and never mixes with others (`pine.<name>`); no `.env`, no orders.
