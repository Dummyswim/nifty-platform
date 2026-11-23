# Build a Python NIFTY distance-and-momentum research feature

You are the implementation engineer working inside my locally self-hosted, TradingView-like NIFTY options analysis platform. Build the feature described below incrementally and integrate it with the existing application. This is a research and paper-analysis project, not authorization to place real broker orders.

## 1. Locate the project and inspect before implementing

Resolve these values from my supplied paths or the current repository:

```text
PLATFORM_REPO_ROOT = the existing platform repository
HANDOFF_ROOT = the extracted nifty-copilot-handoff package
REFERENCE_DIR = HANDOFF_ROOT/reference
CONTEXT_DIR = HANDOFF_ROOT/context
MODE = research and paper analysis only
```

Do not assume the original owner's filesystem exists on this laptop. If the repository or necessary reference files are missing, ask for their locations. Do not search unrelated private folders or retrieve credentials from another application.

Read repository instructions, dependency manifests, architecture, existing market-data adapters, database migrations, chart components, background workers, authentication, and tests. Identify what can be reused. Do not scaffold a competing application over an existing platform.

Give a concise implementation map and then execute the milestones below. Ask only for decisions that materially affect the architecture or unavailable inputs. Continue through independently achievable work; distinguish blocked integration from completed offline work.

## 2. Objective and non-goals

Build a compact, explainable system that measures the relationship between NIFTY price, fast/slow EMAs, and a session anchor, then investigates whether particular entry configurations reach a modest target before a defined stop.

The initial objective is **10 or 20 index points of favourable movement with a 10-15-index-point stop budget**, not a guarantee of capturing every market move. Start with a fixed 12-point stop and separate 10-point and 20-point target experiments.

The user eventually buys CALL or PUT options. Index-direction research and executable option profitability must remain separate until actual option quotes and a fixed contract-selection policy are available.

Do not:

- Claim an inevitable reversal because price is far from an average.
- Claim that a probability score or profitable backtest establishes a proven future edge.
- Keep adding unrelated RSI, ADX, CVD, zone, or candlestick filters until selected historical arrows look profitable.
- Infer special reversal probabilities from price endings such as 40, 70, or 80 without separately designed evidence.
- Convert a bearish index indication into an instruction to sell naked options.
- Automatically modify or merge the supplied Pine strategies into this new engine.
- Add real-order execution, an options-selling system, a full broker terminal, or a large ML platform.

Use a distinct engine identity, for example `distance_entry_research_v1`. Faithful Pine ports, if present, must retain separate identities and results.

## 3. Background and evidence to preserve

The reference files are:

```text
reference/Nifty_VWAP_Spread_Scalper.pine
reference/Balu_Zone_Scalper_v2.pine
```

They provide useful prior art, not proof of predictive power. The first is a strategy; the second is a descriptive indicator with zones, pressure proxies, and path history.

The supplied screenshots show a morning decline, a renewed midday decline while price is already below the session anchor, and an afternoon rebound that starts below that anchor. They illustrate why both mandatory fresh VWAP crossovers and universal maximum-VWAP-distance limits can miss local moves.

The exploratory public-data replay in `context/` found:

| Experiment, target 20 / stop 12 | Trades across 18 evaluated sessions | Mean gross index points/trade | Gross points on 18 Nov 2026 |
|---|---:|---:|---:|
| Anchor crossover with EMA order | 109 | 1.433 | -134.75 |
| EMA-gap re-expansion | 451 | 0.804 | -213.50 |
| EMA-aligned gap re-expansion | 286 | 1.993 | -145.05 |

These are exploratory index-path results, not option P&L, cost-adjusted profits, Pine parity results, or a validated holdout study. Do not optimize toward reproducing a profitable answer.

A concrete illustration from the public 09:30 candle on 18 Nov 2026 is:

```text
Open 25293.95, high 25318.05, low 25289.40, close 25314.55.
Hypothetical bearish entry at open: target 25273.95, stop 25305.95.
The 12-point stop is touched; the 20-point target is not touched in that candle.
The 09:45 close is nevertheless 25222.75.
```

The directional view can be right while the permitted price path loses. Treat entry timing and adverse excursion as central, not secondary.

Use the research harness only as an auditable baseline. Review it before reuse; it is not the production architecture or a full broker emulator.

## 4. Architecture: fit the existing platform

Preferred technologies:

| Layer | Requirement |
|---|---|
| Quantitative core | Python, independent of HTTP frameworks and chart rendering. |
| Existing FastAPI backend | Integrate routers and reusable services; run substantial backtests in a worker, not the async request loop. |
| Existing NestJS backend | Keep NestJS as the application/API/WebSocket gateway; call a Python analysis service or worker through the existing transport. Do not reimplement quantitative formulas in TypeScript. |
| New approved backend | Prefer FastAPI; do not build both FastAPI and NestJS without an existing need. |
| Storage | PostgreSQL, with TimescaleDB for appropriate time-series tables. |
| Cache/streaming | Redis for cache, live fan-out, and an existing supported job/event mechanism. PostgreSQL remains the durable source of truth. |
| Frontend | Existing React/Next.js/TypeScript application. |
| Charts | TradingView Lightweight Charts. Add ECharts only for a clear unmet analytical visualization; use Highcharts only if its licensing is explicitly acceptable. |

Inspect installed versions and use their actual APIs. Lightweight Charts is a renderer, not the TradingView hosted product, Pine runtime, or a data entitlement. Preserve required license notices and attribution.

Reuse shared market-data and indicator primitives from faithful Pine ports where semantics match. Keep deliberate differences explicitly named. Avoid unnecessary microservices, new message brokers, or duplicate job systems.

## 5. Data and instrument contract

Support recorded CSV/JSON data first, then a Dhan historical/live adapter using credentials explicitly configured by the operator.

Store enough instrument metadata to identify the actual asset:

```text
provider, exchange, exchange_segment, security_id, instrument_type,
symbol, underlying_id, expiry, strike, option_type,
tick_size, lot_size, currency, instrument_metadata_version
```

Use the provider's instrument master. Never construct valid contracts from guessed expiry weekdays, assumed lot sizes, or screenshot labels. Historical contract selection must use information available at that historical time.

Every bar must include:

```text
instrument_id, provider, timeframe, bar_start_utc, bar_end_utc,
open, high, low, close, volume,
volume_kind, finalized, received_at_utc, revision, quality_flags
```

Record whether volume is exchange-reported, absent, synthetic, or proxy-derived. Missing volume is not automatically a valid zero-volume trade.

Store UTC timestamps and display Asia/Kolkata time. Explicitly distinguish candle start, candle completion, signal availability, entry, and exit. A 09:30 one-minute candle is not complete at 09:30.

Use an exchange calendar with regular sessions normally 09:15-15:30 IST; handle holidays, special sessions, shortened sessions, and historical calendar changes. Do not use the laptop timezone as the trading calendar.

Validate duplicates, ordering, OHLC relationships, timestamp alignment, missing intervals, stale feeds, and unexpected session bars. A public response may append a current quote outside the requested historical range; filter and report this rather than accepting it as a historical candle.

Never silently interpolate OHLC, manufacture missing option quotes, or turn partial histories into apparently complete tests. Mark affected results unavailable or explicitly partial.

Persist raw input or a reproducible snapshot with source identifiers and checksums. Define a late-data/correction policy. Preserve the as-known signal/event history; a corrected historical bar must not silently rewrite an already issued live signal.

## 6. Indicators and compact features

Initial research settings:

```text
Chart timeframe: 1 minute
Fast EMA: 9
Slow EMA: 21
ATR: 14, Wilder smoothing
Rate window: 3 completed bars
Session anchor: explicit VWAP or explicitly labelled fallback
```

Document indicator seeding and warm-up. Warm EMAs from prior history, not future bars. Retain the research harness's session-adjusted true range if reproducing that experiment: the first session bar uses high-low rather than an overnight-gap true range. Name this variant; do not confuse it with standard ATR or Balu's ATR.

For anchor calculation use session HLC3:

```text
Usable same-instrument volume:
    anchor = sum(HLC3 * volume) / sum(volume)
No usable volume:
    anchor = equal-bar session mean of HLC3
```

Label the latter `TWAP / equal-bar session average`, not genuine VWAP. A spot series weighted by futures volume is `proxy weighted`, not spot traded VWAP or the futures' own VWAP. Do not subtract an unadjusted futures VWAP from spot prices and call the difference pure spot extension.

Begin with three signed coordinates:

```text
P = completed close
F = EMA9
S = EMA21
V = session anchor
A = prior completed bar's ATR, valid and positive

D = (P - V) / A       # session position
E = (P - F) / A       # immediate extension
M = (F - S) / A       # EMA separation

price_to_slow = E + M
fast_to_anchor = D - E
slow_to_anchor = D - E - M
```

The derived distances are not independent confirmations. Preserve raw distances in index points alongside normalized values.

Calculate relative rates from raw spreads, scaling once:

```text
anchor_rate = ((P-V)[t] - (P-V)[t-k]) / (k * A)
gap_rate    = ((F-S)[t] - (F-S)[t-k]) / (k * A)
```

These rates are ATR per bar, not price velocity in points per second. If providing points per minute, explicitly divide by elapsed time. Do not bridge the session-anchor reset when calculating anchor rates.

This definition deliberately differs from the original NVS `devAtr[t] - devAtr[t-k]`. Keep the research and compatibility calculations separately named.

An expanding bearish gap has negative separation becoming more negative. Do not confuse signed movement with an increasing absolute distance. Handle zero/invalid ATR as unavailable rather than emitting infinities or an arbitrary strong signal.

## 7. Engines and research hypotheses

First implement the three simple baselines from section 3 with exact, documented causal timing. Use the context harness and results as a reproducibility aid, not a financial acceptance target.

For the re-expansion baseline:

```text
Bull candidate:
    current gap_rate > 0 and prior gap_rate <= 0
    and close > EMA9
Bear candidate:
    current gap_rate < 0 and prior gap_rate >= 0
    and close < EMA9

EMA-aligned variant additionally requires:
    EMA9 > EMA21 for bull, EMA9 < EMA21 for bear
```

Do not add filters to these benchmark definitions. A new condition creates a separately named experimental variant.

Next investigate a separate **setup -> armed resumption -> entry -> exit** state machine. Keep it small:

- Context describes continuation, counter-session rebound, or mixed movement; session VWAP position is not automatically a mandatory crossover gate.
- A completed pause/pullback can arm a directional resumption level from already known candle prices.
- A candidate entry occurs on a predefined resumption trigger, not merely when an EMA gap becomes visually large.
- Any pullback invalidation level, setup expiry, and one-shot rearm rule must be frozen at arming and fully specified before evaluation.
- Compare completed-close confirmation against conditional intrabar triggering as separate execution modes. Intrabar triggering requires suitable lower-timeframe/tick evidence.
- Skip a setup that cannot respect the specified risk budget; never widen an active stop to rescue it.

Before coding this new state machine, write a short exact specification covering formation, direction, trigger level, invalidation, timeout, cancellation, and rearming. Ask for approval only where a genuine product choice remains unresolved. Do not claim that this new hypothesis has already passed the baseline tests.

A plain opposite-colour candle is neither guaranteed invalidation nor permission to ignore a stop. A profitable exit is not automatically a reverse entry.

## 8. Outcome and execution semantics

Keep a reference baseline configuration:

```text
Targets: 10 and 20 index points, separate experiments
Stop: 12 index points; explicit experiments may examine 10-15
Maximum hold: 10 minutes
Entry window: actual reference entry time 09:30-14:45 IST
Flatten: no overnight positions; explicit session cutoff
One position at a time per instrument/strategy instance
No breakeven, partial exits, pyramiding, or trailing stop in the initial baseline
```

Signals use only information known at decision time. A closed-bar entry fills no earlier than the next available event/bar open; do not buy retrospectively at a favourable signal candle price.

For a next-open baseline, anchor target and stop to that actual reference entry. If the next price gaps, apply documented gap rules. Stop loss is a trigger/risk budget, not a guaranteed maximum realized loss.

Keep three principal outcomes:

```text
TARGET_FIRST
STOP_FIRST
TIME_EXIT, with actual directional return at the time exit
```

Track ambiguous bars and data/session interruptions separately. Do not discard them from denominators to inflate win rates.

With OHLC only, if both barriers lie within a bar, order is unknown. Default the conservative research replay to stop first and retain an ambiguity flag; optionally report bounds. Use finer data only when genuinely available. Never invent a tick path.

Stops/targets may be checked intrabar even when entry signals are bar-close based. Do not wait until candle close to recognize a known stop crossing. Conversely, do not use a bar's later high to tighten a stop retrospectively against that same bar's earlier low.

For intrabar exits, record the containing bar and unknown exact fill time unless finer data establishes it. A time exit at bar close has an actual close timestamp.

Measure MAE, MFE, time-to-target, time-to-stop, first-minute adverse movement, holding time, and drawdown with explicit definitions and path-resolution limitations.

## 9. Probability estimation: later, not fabricated at launch

Do not display invented percentages before a model has been fitted and evaluated. Baseline labels must say `experimental`, `watch`, or `paper`, not imply a verified edge.

After deterministic data and replay are correct, evaluate a small interpretable statistical model using the compact distance/rate features. Retain volatility and time-of-day context: fixed point barriers have different meanings under different volatility and session-anchor ages.

Prefer a simple regularized model or another small, explainable model justified by validation. Avoid arbitrary hand-picked weights labelled as probabilities, large feature stacks, and deep learning by default.

Estimate target, stop, and timeout outcomes coherently, including timeout payoffs. For one consistent unit system:

```text
expected_outcome =
    p_target * target
    - p_stop * stop
    + p_timeout * expected_timeout_return
    - expected_cost
```

This is an explanatory formula; actual evaluation must include gaps, variable fills, and the full exit policy. Do not apply a two-outcome break-even win-rate formula to a strategy with timeouts, partial exits, or breakeven exits.

Use chronological development, validation, and untouched evaluation periods. Purge overlapping outcome windows across boundaries. Fit scalers, feature transforms, thresholds, and calibration only on allowed training/validation data.

Record every tested variant. Use session-aware uncertainty estimates where defensible; overlapping minute labels are not independent trades. Report calibration/reliability, sample support, and out-of-distribution conditions. A nominal minimum sample count is not proof of significance.

Freeze a selected model/configuration before forward paper evaluation. If no stable advantage survives evaluation, deliver the working research system with `edge not established`; do not manufacture a profitable strategy.

## 10. Separate index research from option execution

Use the index for directional features initially. Add an explicitly configured contract policy before evaluating CALL/PUT returns:

- Selected expiry and strike or a clearly defined as-of selection rule.
- Contract identity and actual historical availability.
- Lot size, tick size, bid/ask, quote age, liquidity, fees, and slippage assumptions.
- Buy-side fills based on executable ask/available execution evidence, sell-side exits on bid/evidence, not automatically LTP or midpoint.
- Accurate reporting of index points, premium points, rupees, and quantity as different units.

Do not reconstruct option prices from index candles and call them real option data. Do not reuse today's chosen strike retrospectively across all history.

An index-triggered paper option exit is a synthetic software trigger, not automatically a broker-held option stop. Future real-order work would require a separate authorization and risk design; it is out of this scope.

## 11. Persistence, API, and streaming

Adapt names to existing conventions. Expected durable concepts include:

```text
instrument/version metadata
raw market events or data-snapshot references
OHLCV bars and revisions
engine configurations and source fingerprints
feature/state snapshots
signal and drawing events
research jobs and dataset versions
paper trades and fills
evaluation reports and model artifacts
```

Use migrations and appropriate indexes/hypertables. Time-series uniqueness must include source/instrument/timeframe/time and the chosen revision policy. Do not impose a uniqueness index incompatible with a Timescale partition key.

Provide asynchronous job submission and status/results endpoints for substantial backtests. Provide paginated bar/trade retrieval, configuration endpoints, and a typed WebSocket stream for live state updates.

Every relevant event should carry:

```text
schema_version, event_id, event_type, engine_id, engine_version,
config_hash, instrument_id, source_id, timeframe,
event_time_utc, available_at_utc, bar_start_utc, bar_end_utc,
confirmed_or_provisional, price_basis, payload
```

Use deterministic idempotency keys and checkpoint/cursor recovery. Duplicate or replayed input must not create duplicate paper entries. Redis loss must not silently lose the authoritative audit history.

Never silently convert worker failures into empty successful results. Surface data gaps, stale feeds, invalid configurations, and rejected jobs in both API and UI.

## 12. Frontend requirements

Integrate with the current UI rather than introducing a second app.

- Provide index, selected CALL, and selected PUT charts with synchronized time/crosshair navigation where practical.
- Render EMA9, EMA21, and the correctly named session anchor.
- Add compact distance/rate panes or a small diagnostic panel, not a cluttered stack of indicators.
- Distinguish watch/setup, armed trigger, paper entry, exit, target, stop, and invalidation markers.
- Show engine identity, configuration, price basis, anchor kind, confirmation status, and data freshness.
- Clearly distinguish `BEARISH INDEX / PUT CANDIDATE` from an order to short the displayed instrument.
- Show target/stop/time outcome counts, gross/net assumptions, MAE/MFE, drawdown, and unavailable/ambiguous results.
- Provide replay controls, saved parameter sets, and downloadable research/trade results.
- Display pending/provisional updates separately from confirmed history; do not retroactively place a signal where it was not yet knowable.
- Avoid claiming that index/CALL/PUT agreement supplies three independent confirmations.

Keep units, timezone, stale-feed warnings, and research status visible. Reconnection must recover a consistent snapshot before applying incremental updates.

## 13. Operational requirements

Use the repository's Python environment/package manager and existing frontend lockfile. Do not copy the original owner's virtual-environment path.

Provide documented local startup, preferably through the existing Docker Compose setup. Add only needed services. Configure environment variables with a secret-free example file. Keep Dhan tokens on the backend, out of source control, frontend bundles, URLs in logs, and screenshots.

Bind a new development service to localhost by default. Preserve or add appropriate authentication/CORS controls if intentionally exposed on a LAN.

Handle token expiry, reconnection/backoff, rate limits, instrument refresh, delayed packets, duplicate packets, clock skew, and laptop sleep. Do not present an analysis calculation as proof that a feed or execution connection is healthy.

Confirm current Dhan data entitlements and documentation during implementation. Do not hardcode today's API limits as permanent facts.

## 14. Roadmap and milestone deliverables

| Milestone | Work | Exit criterion |
|---|---|---|
| 0. Repository and data audit | Resolve paths; inventory existing stack, data, calendar, and shared primitives. | Integration map, missing-input list, and exact initial experiment specification. |
| 1. Canonical data and core | Ingestion/replay adapter, data validation, Python indicators/features, snapshots. | Deterministic outputs on fixed fixtures; explicit anchor/volume/time semantics. |
| 2. Reproducible baselines | The three specified entry rules and conservative target/stop/time replay. | Trade log and report reproduce documented assumptions; no lookahead. |
| 3. Platform integration | API/worker/database/Redis integration and charts/state overlays. | A saved dataset can be analyzed and replayed end-to-end in the UI. |
| 4. Entry-location experiment | Specify and implement the separately versioned pullback/resumption candidate. | Fully causal state transitions, cancellation, rearming, and risk-budget tests. |
| 5. Statistical evaluation | Chronological comparisons, uncertainty, costs, optional small calibrated model. | Honest report that can conclude no edge; no optimized-on-test claims. |
| 6. Live paper operation | Dhan data adapter, checkpoints, reconnect recovery, paper events. | Repeatable paper results with no duplicate entries or real orders. |

Do not make model profitability a prerequisite for delivering a useful, correct analysis platform.

## 15. Required tests and success criteria

Engineering acceptance:

- Same finalized data/configuration gives equivalent batch, incremental, and restart/replay outputs.
- Future-bar changes do not change previously confirmed causal signals.
- Midnight/session boundaries, holiday gaps, missing volume, zero-range bars, and insufficient warm-up are handled explicitly.
- Duplicate/out-of-order inputs, reconnects, and repeated job submission do not duplicate results.
- Signal-close versus next-open timing, long/short symmetry, stop gaps, same-bar ambiguity, and timeout-bar counting are covered.
- No retrospectively tightened stop can benefit from a bar's future path.
- Index and premium units cannot be accidentally mixed.
- APIs, migrations, frontend types, and existing tests pass; no unrelated regressions.
- A reproducible fixture runs from documented commands; UI screenshots show real fixture data, not invented profits.
- A 100,000-bar single-instrument replay completes without request-loop blocking or unbounded memory growth. Measure and report hardware/runtime/memory; do not invent latency guarantees.

Research acceptance:

- Results include all eligible outcomes, failures, timeouts, ambiguous cases, and cost assumptions.
- New hypotheses are compared with fixed baselines on later, unused sessions.
- Any probability display has documented training/calibration/support and can abstain.
- Financial readiness remains `not established` unless separate, predefined out-of-sample and paper criteria are actually met.
- No claim of capturing every move, guaranteed stop execution, or inevitable reversal appears in the UI or documentation.

## 16. Final implementation handoff

Provide the implemented files, architecture/integration summary, database migrations, API/event contracts, parameter schema, local startup instructions, tests and actual results, a reproducible example, and known limitations.

Separate completed engineering, verified data parity, exploratory research results, and blocked/unsupported capabilities. Do not create a real broker order, open a pull request, or publish private market/account data merely to demonstrate completion.

Useful official references to verify against current versions:

- https://dhanhq.co/docs/v2/
- https://dhanhq.co/docs/v2/live-market-feed/
- https://dhanhq.co/docs/v2/historical-data/
- https://dhanhq.co/docs/v2/authentication/
- https://tradingview.github.io/lightweight-charts/
- https://www.tradingview.com/pine-script-docs/
