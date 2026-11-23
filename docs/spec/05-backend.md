# Backend, API, storage

## Layout (`backend/src/nifty/`)
`contracts/ · timeutil.py · marketdata/{base.py, providers/{csv_replay,kite}.py} · engines/{base.py, pinekit/, nvs/, balu/, research/} · execution/ · analytics/ · db/ (models; Alembic in backend/alembic) · api/ · worker/ · collector/ · cli.py`
Repo root: `backend/ web/ deploy/ fixtures/{bars,tv_golden,kite_recorded}/ tools/ data/calendar.yml Makefile Makefile.local(gitignored) .env.example`.
Import rule (tested): `contracts, timeutil, engines, execution, analytics` never import `api, db, sqlalchemy, fastapi, redis`.

## Provider interface (D01)
`MarketDataProvider`: `list_instruments()`, `historical(instrument, tf, from, to) -> Iterable[Bar]`, `stream(instruments, mode) -> AsyncIterator[Tick]`, `status()`. Adapters: `CsvReplayProvider` (C01), `KiteProvider` (C07/C08), chosen by `MARKET_DATA_PROVIDER`. Error taxonomy: `AUTH_EXPIRED, RATE_LIMITED, ENTITLEMENT, NETWORK, BAD_DATA`.

## Compose (`deploy/docker-compose.yml`)
`db` (timescale/timescaledb, pinned tag) · `redis` (pinned) · `api` (uvicorn) · `worker` · `collector` (profile `live`) · `web`. Every published port bound to `127.0.0.1`; healthchecks on db/redis/api; named volumes; env from `.env`. Kubernetes-ready: 12-factor env, `/healthz` liveness, `/readyz` (db + migrations), stateless api/worker, no host paths except volumes.

## Jobs (D07)
`jobs(id, kind, key UNIQUE, payload JSONB, status queued|running|done|failed, attempts, error, result_ref, created_at, started_at, finished_at, heartbeat_at)`. The worker takes work with `FOR UPDATE SKIP LOCKED`, heartbeats, requeues stale jobs, and stores failures (never an empty "success"). Resubmitting the same `key` returns the existing job/result.

## Tables
`instruments · instrument_masters (daily dump, versioned) · bars (hypertable; unique incl. bar_start_utc, revision) · ticks (hypertable) · calendar_days · datasets (snapshot_id, sha256, range) · engine_configs (config_hash, params JSON) · engine_runs (run_id, engine_id, version, config_hash, source_id = snapshot_id|live, panel JSONB = last bar's panel) · plot_points (run_id, bar_start_utc, values JSONB) · jobs · backtests · trades · events (JSONB) · overlay_elements · kite_tokens (encrypted) · prefs · drawings · research_runs/research_labels (C14)`. `user_id` (default 1) on prefs/drawings/engine_configs/backtests (D17). One Alembic migration per chunk that adds tables.

## API (`/api/v1`; OpenAPI → TS types, D05; everything except `healthz` needs the session cookie)
- `healthz`, `readyz`.
- `auth/login|logout|me`: scrypt hash in `APP_PASSWORD_HASH` (`python -m nifty.cli hash-password`); HMAC-signed httpOnly SameSite=Lax cookie, 12 h; JSON-only POST + Origin check; WS uses the same cookie.
- `kite/login-url|callback|status`: the callback exchanges the token server-side, then 303-redirects to the UI by absolute URL (first `APP_ORIGINS` entry).
- `instruments`; `bars` (columnar `{t,o,h,l,c,v,flags}`, default limit 5000, time cursor); `datasets/import`.
- `engines` (list + params JSON Schema); `engines/{id}/run` (job); `overlays`, `plots`, `events` (by snapshot or live range).
- `prefs`, `drawings`.
- `backtests` (create → job; list; get; `trades`; `audit/{trade_id}`; `analytics`; `export?fmt=csv|xlsx|json`).
- `collector/status`; `options/expiries|chain|contract-bars` (C12); `research/runs` (C14).
- WS `/ws/v1/stream`: `snapshot` first, then `bar`, `event`, `status`, `panel`; the client resubscribes with its last cursor and the server resends from it.

## Kite (read-only, D19/D28; C07 records verified facts in `docs/spec/08-kite-verified.md`, ≤60 lines)
- Login: the user opens the Kite login URL → redirect to `KITE_REDIRECT_URL` with `request_token` → server POSTs `/session/token` with checksum `sha256(api_key + request_token + api_secret)` → `access_token`, stored encrypted with `APP_SECRET_KEY`. Tokens expire daily (~06:00 IST): the UI shows "Connect Kite"; never automate login.
- REST headers `Authorization: token <api_key>:<access_token>`, `X-Kite-Version: 3`.
- Historical: `/instruments/historical/:instrument_token/:interval?from&to[&continuous][&oi]` (`yyyy-mm-dd hh:mm:ss`); intervals `minute 3minute 5minute 10minute 15minute 30minute 60minute day`; candle = `[timestamp (+0530), o, h, l, c, volume(, oi)]`.
- Verified in C07 (see 08): rate limits 3 req/s historical, 1 req/s quote, 10 req/s other. Per-request day limits (minute 60, 3/5/10m 100, 15/30m 200, 60m 400, day 2000) and the paid Connect plan are NOT on the docs pages: assumptions until `make kite-smoke`.
- Instrument master: CSV `instrument_token, exchange_token, tradingsymbol, name, expiry, strike, tick_size, lot_size, instrument_type, segment, exchange`. Live contracts only ⇒ cache the dump daily (D10/D12).
- WS `wss://ws.kite.trade`: modes `ltp|quote|full`; binary packets (LTP 8 B; quote 44 B, index 28 B; full 184 B, index 32 B); prices in paise (÷100; currency segment ÷1e7); 1-byte heartbeats; ≤3 connections per key, ≤3000 instruments per connection. Bid/ask/OI need `full` (depth): subscribe the option window in `full`, the index in `ltp`/`quote`.
- Tests use handcrafted/recorded packets (`fixtures/kite_recorded`) and a fake transport; no network.

## Collector and live runner (C08)
Ticks → batched insert → Redis pub/sub → 1m bar builder (volume = delta of the day's traded volume when present; the index has none ⇒ `absent`). A provisional bar is published at most every 250 ms and finalizes at the minute rollover (by tick exchange timestamp). A tick-silence watchdog marks `stale`. On reconnect (exponential backoff + jitter) backfill the gap from historical minute candles. After 15:35 IST an EOD reconcile fetches the day's 1m candles and writes differences as `revision+1` with `reconciled`.
The runner feeds each finalized bar (and resampled buckets) to enabled engines, persists plots/events/overlay_elements, publishes them on the WS (provisional outputs flagged), and restores from `snapshot()` or replays the warm-up window after restart (D14).
