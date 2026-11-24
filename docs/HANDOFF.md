# HANDOFF (webapp Deliverables 1–11)

## 1. System architecture
```
 Kite REST/WS (read-only)        CSV import / demo replay
        |                                |
        v                                v
  Collector (ticks->1m bars) --> Postgres/Timescale (source of truth: bars, ticks, runs, jobs)
        |  \--> engines (incremental on_bar)        ^        ^
        v                                           |        |
      Redis pub/sub (cache + live fan-out)     Worker (jobs: backtest, engine_run, research_run)
        |                                           |
        v                                           v
   FastAPI  /api/v1/*  + /ws/v1/stream  <-----------+      Web (React/TS, lightweight-charts, ECharts)
```
Quant core `nifty.*` (engines, execution, analytics, options, pinekit) imports no HTTP/ORM. Losing Redis loses no audit data (D03).

## 2. Database schema (Alembic 0001–0008)
`instruments`, `bars` (1m, versioned revisions), `datasets` (snapshots), `calendar_days`, `ticks` (hypertable),
`engine_configs`, `engine_runs`, `plot_points`, `events`, `overlay_elements`, `jobs` (SKIP LOCKED queue),
`backtests`, `trades`, `drawings`, `prefs`, `instrument_masters`, `kite_tokens` (Fernet), `collector_status`,
`research_runs`, `research_labels`. Time is UTC (timestamptz); IST only at the edges; units suffixed `_pts/_inr/_prem/_r`.

## 3. API design (`/api/v1`, cookie session, POSTs check Origin)
auth (`login`, `logout`, `me`) · `instruments`, `datasets/import`, `bars` · `engines`, `engines/{id}/run` ·
`plots`, `events`, `overlays` (by run) · `jobs/{id}` · `backtests` (+ `trades`, `analytics`, `audit/{trade}`, `export`) ·
`drawings`, `prefs` · `options/{expiries,chain,contract-bars}` · `kite/{login-url,callback,status,...}` ·
`research/runs` (+ `labels`) · WebSocket `/ws/v1/stream` (cookie auth). `/healthz`, `/readyz` open. Types are generated
from OpenAPI (`make api-types`); no schema pages are served.

## 4. Frontend wireframes
```
Chart                                   Options                         Backtests + audit
+-----------------------------------+   +--------------------------+    +----------------------+------------+
| NIFTY 1m  [TF][Indicators][Replay]|   | expiry kind | strike type|    | form: engine tf mode | Trade audit|
| tools |  candles + VWAP/EMA/zones |   | chain: CE | strike | PE  |    | metrics cards        | levels,    |
|       |  markers, drawings        |   | ATM row highlighted      |    | trades table (sort)  | events,    |
| panel |  engine cards (panel())   |   | contract chart + OI      |    | row -> audit drawer  | open chart |
+-----------------------------------+   +--------------------------+    +----------------------+------------+
Analytics: equity/drawdown/session histogram (ECharts) · Research: run form, CI chart, variant table,
verdict banner (conditions passed/failed), label drilldown -> index chart · Settings: Kite status/connect, options r, strikes.
```

## 5. Docker Compose
`deploy/docker-compose.yml`: `db` (Timescale), `redis`, `api`, `web` (nginx), plus `worker` and `collector` as compose profiles;
every published port is `127.0.0.1`-bound (tested). Images install `backend/requirements.lock` (`make lock`) and
`npm ci`. `make up/down/ps/logs/backup`. **Not verified: no Docker on the dev host** (compose `config`, builds, `make up`).

## 6. Zerodha/Kite integration
Read-only httpx client with an endpoint allowlist, rate limiter and secret redaction; daily instrument master versioned
(`instrument_masters`); token via browser login, stored encrypted, expires 06:00 IST; WS binary parser, collector
(ticks -> 1m bars -> engines -> DB -> Redis), reconcile/backfill jobs, option-window recording planner. Verified live 2026-11-23:
profile, master, 1m candles (`make kite-smoke`). Unverified: live WS stream, option window recording, backfill against real Kite.

## 7. Pine conversion design
Pine source beats port maps (`docs/pine/`). Each script = an incremental engine with `Params` (Pine defaults) + `ui` split,
JSON-safe snapshot/restore, plots/overlays/events on the shared contracts, `pinekit` primitives. Checklist: `docs/engines/PORTING.md`.
Done: `pine.nvs_scalper`, `pine.balu_zone` (15-step registry). Golden TradingView exports pending (see EVIDENCE).

## 8. Backtesting engine
Signal at closed bar t, fill at open t+1; `tv` mode (BrokerEmulator, Pine strategy semantics) and `conservative` (stop wins
ambiguous bars, explicit `cost_pts`). Same inputs => same `backtest_id`. Metrics, exports (CSV/XLSX/JSON), CE/PE paper mapping at
recorded ask/bid (60 s staleness, `no_quote`). Research: `research.distance_entry_v1`, 50/25/25 session split with purge,
session-clustered bootstrap CI, leave-one-session-out, verdict `candidate|inconclusive|edge_not_established` (>= 60 sessions).

## 9. Audit dashboard
Backtest row -> audit drawer (entry/stop/target/exit, reason, P&L, events around the trade) -> "Open on chart" (overlays) or
replay from the signal bar. Research label drilldown shows diagnostics and event sequence.

## 10. MVP roadmap (done vs not)
Done: C01–C15 (data, calendar, engines NVS/Balu/research, jobs, backtests, chart UI, replay, Kite client, live collector,
options dashboard, research pipeline, hardening). Not done: golden parity for both Pine ports, live-market verification,
Docker verification, calendar holiday confirmation, calibrated research model (deferred by spec).

## 11. Production roadmap
1. Export TradingView goldens, close parity gaps, then flip `golden_tv`. 2. Run live for several weeks; verify WS packets,
reconnect, option recording. 3. Docker stack on a host with Docker; TLS reverse proxy if exposed beyond localhost.
4. Multi-user auth, secrets manager, scheduled `make backup`, monitoring on `/readyz` and collector status.
5. More research data (>= 60 sessions) before reading any verdict. 6. Additional brokers behind `MarketDataProvider` (read-only).

## Backup / restore
`make backup` writes `backups/nifty-<ts>.sql.gz` (gitignored; needs the Compose db). Restore into an empty database:
`gunzip -c backups/<file>.sql.gz | psql "$DATABASE_URL_WITHOUT_+psycopg"`, then `make migrate` (no-op at head). Native dev DB:
`pg_dump "$URL" | gzip > backups/x.sql.gz` the same way. Keep `.env` (APP_SECRET_KEY decrypts stored Kite tokens) separately.

## Daily routine
`make start ARGS=--live` -> Settings -> Connect Kite (after 06:00 IST) -> Chart. Read `docs/STATE.md` before changing anything.
