# Contracts (module `nifty.contracts`, Pydantic v2; one set for every engine)

Units: suffix `_pts` index points · `_prem` option premium · `_inr` rupees · `_r` R multiples · `_bps`. Use NewTypes; mixing raises `UnitMismatch` (tested).

## Instrument
`instrument_id` (internal, e.g. `kite:NSE:NIFTY 50`) · `provider` (`kite|csv`) · `provider_token` (Kite instrument_token) · `exchange` · `segment` · `instrument_type` `INDEX|EQ|FUT|CE|PE` · `tradingsymbol` · `underlying` · `expiry` · `strike` · `option_type` · `tick_size` · `lot_size` · `currency` · `metadata_version` · `provider_meta` (JSONB: exchange_token, name…).
NIFTY 50 is resolved from the daily Kite master (exchange NSE, segment INDICES). Never hardcode its token.

## Bar
`instrument_id, provider, timeframe (1m 3m 5m 10m 15m 30m 1h 1d), bar_start_utc (inclusive), bar_end_utc (exclusive), open, high, low, close, volume, volume_kind (exchange|absent|synthetic|proxy), finalized, received_at_utc, revision (0 = first), quality_flags`.
`quality_flags` vocabulary: `off_grid gap_before stale zero_range partial_bucket volume_absent calendar_unverified reconciled`.

## EngineEvent (envelope)
`schema_version, event_id (uuid5 of engine_id|config_hash|instrument_id|timeframe|bar_start_utc|event_type|seq), event_type, engine_id, engine_version, config_hash, instrument_id, source_id (snapshot_id | "live"), timeframe, event_time_utc, available_at_utc, bar_start_utc, bar_end_utc, confirmed_or_provisional, price_basis, payload`.
`available_at_utc` = earliest instant a live consumer could know it (bar_end for close-based events). Replay reveals by `available_at_utc <= cursor`.
`event_type` examples: `signal entry exit stop_update zone_update alert research.watch research.armed research.entry research.exit research.invalidated`.

## Engine protocol
```python
class Engine(Protocol):
    id: str; version: str
    default_timeframe: str               # the timeframe it is designed for (NVS "5m"); outputs are time-anchored, so any chart timeframe can display them
    Params: type[BaseModel]              # sub-model `ui` (colours, toggles) is excluded from config_hash
    plots: list[PlotSpec]                # name, kind line|step|hist|area, role, pane overlay|own
    warmup_bars: int
    def __init__(self, params, ctx: EngineContext): ...
    def on_bar(self, bar: Bar) -> EngineOutput: ...          # finalized bars only
    def on_provisional(self, bar: Bar) -> EngineOutput: ...  # optional; must not mutate confirmed state
    def snapshot(self) -> dict: ...
    def restore(self, snap: dict) -> None: ...
    def panel(self) -> dict | None: ...
# EngineOutput = {plots: dict[str, float | None], events: [EngineEvent], overlay_ops: [OverlayElement], trades: [TradeRecord]}
```
`EngineContext`: instrument, timeframe, mintick, session calendar, plus runner-supplied aux data (prior-day aggregates, 1m sub-bars of the current bar, completed HTF bars, proxy volume). Engines never read the wall clock, DB or network.
`config_hash = sha256(canonical_json({engine_id, engine_version, params without ui}))`.

## OverlayElement (renderer-agnostic, event-sourced)
`id, ver, deleted, avail_at_utc, engine_id, kind, t0, t1|null, p0, p1|null, style{role,…}, text, meta`.
`kind`: `line step_line hline band zone marker label region`. Zone `meta`: `status active|mitigated|projected`, `tier`, `top`, `bot`. Colours are role tokens (`demand supply neutral bull bear info warn`); the UI maps them to a theme.
Per `id` the renderer shows the latest `ver` with `avail_at_utc <= cursor`; `t1 = null` ⇒ extends to the cursor. Replay = reveal the causal run's stored outputs by `available_at_utc`; never recompute.
Per-bar series are `plots`, not overlays; `panel()` is a dict of rows `{label, value, role}`.

## TradeRecord
`trade_id, engine_id, instrument_id, side, signal_bar_start, entry_time, entry_px, exit_time, exit_px, exit_reason, qty, gross_pts, cost_pts, net_pts, r_multiple, mae_pts, mfe_pts, bars_held, execution_mode, flags`.
Option paper trades add `contract_id, entry_prem, exit_prem, pnl_inr, roi_pct` and `synthetic=true` when the exit was index-triggered.
