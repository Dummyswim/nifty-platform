# NIFTY Platform

Self-hosted, TradingView-like research app for NIFTY 50 and its options: a Python quant core
(Pine ports, backtests, research statistics), FastAPI, Postgres/Timescale, Redis and a React/TypeScript
chart UI. Data comes from Zerodha Kite (read-only) or CSV replay.

**Safety: read-only. The app never places, modifies or cancels orders** (no order, GTT or basket
endpoints exist; a test greps the source for them). Research output is descriptive, labelled
experimental, and "edge not established" is a valid result.

## Quickstart (native, no Docker)
1. `make init-env` creates `.env` from `.env.example`; fill in `KITE_API_KEY`/`KITE_API_SECRET`
   (only needed for live data) and run `make hash-password` to set `APP_PASSWORD_HASH`. Never commit `.env`.
2. `make start` runs migrations, the API, the worker and the web app on one command, then prints
   `http://127.0.0.1:8080`. Add `ARGS=--live` for the live collector. Log in with your app password.
3. Without Kite: import `reference/oracle` style 1m CSVs (`POST /api/v1/datasets/import`) or run `make demo`.

## Daily Kite login
The Kite access token expires every day at 06:00 IST. Open **Settings → Connect Kite**, sign in at Zerodha,
and you are redirected back; the token is stored encrypted. `make kite-smoke` checks the connection.

## Make targets
`start` run everything · `check` ruff, mypy, pytest, tsc, vitest · `test T=…` one test selection ·
`e2e` Playwright smoke · `bench` engine throughput · `parity E=<engine>` golden comparison ·
`migrate` · `api-types` regenerate TS types · `lock` pin Python deps · `backup` pg_dump to `backups/` ·
`up`/`down`/`ps`/`logs` Docker Compose stack · `live`, `demo`, `kite-smoke`, `bars`, `db-q`.

## Docs
`docs/HANDOFF.md` (architecture, schema, API, wireframes, roadmap) · `docs/EVIDENCE.md` (what is verified)
· `docs/STATE.md` (build log) · `docs/engines/` (engine notes, `PORTING.md`) · `docs/spec/` (decisions D01…).
