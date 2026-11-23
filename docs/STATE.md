# STATE (≤150 lines; prune every session)

next_chunk: C02
last_update: 2026-11-23 (C01)
env: provider=kite · docker=no · db=native(WSL pg18.7+timescaledb 2.32.1, redis 8.0) · golden_tv=none · kite_creds=none

## Chunks (status: pending | partial | done; partial needs resume_at)
| id | status | notes |
|----|--------|-------|
| C00 | done | scaffold, compose, make tools |
| C01 | done | data core, CSV replay |
| C02 | pending | engine framework, pinekit, broker emulator |
| C03 | pending | NVS port |
| C04 | pending | backtests, audit, analytics, export |
| C05 | pending | UI chart core |
| C06 | pending | UI indicators, replay, audit/analytics (MVP) |
| C07 | pending | Kite REST + instrument master |
| C08 | pending | Kite live collector + live engine runner |
| C09 | pending | Balu 1: params, levels, golden, moving line |
| C10 | pending | Balu 2: zones, location, pressure, sweeps |
| C11 | pending | Balu 3: path history, panel, alerts |
| C12 | pending | options dashboard, CE/PE paper mapping |
| C13 | pending | research engine: features, baselines, armed, outcomes |
| C14 | pending | research runs, statistics, verdict, UI |
| C15 | pending | hardening, lockfiles, handoff |

## Interfaces (one line per module/CLI/endpoint a later chunk uses)
- `python -m nifty.cli hash-password|openapi`; `nifty.config.get_settings()` (fields = `.env.example` keys, lower-case); `nifty.db.session.get_engine()` (lazy, lru_cache); `nifty.db.base.Base`, `nifty.db.models.Pref`
- `nifty.api.main:create_app` (factory); root `/healthz`, `/readyz` (503 if DB down or alembic != `HEAD_REVISION` in api/main.py: derived from alembic scripts); `/api/v1/auth/login|logout|me`; `nifty.api.auth.require_user` guards every later route
- `nifty.security`: scrypt `hash_password/verify_password`, `sign_session/read_session`
- `nifty.contracts`: Bar, Instrument, ValidationReport(+Exclusion, Gap{day,from_ts,to_ts,missing}, SessionInfo{date,first,last,n}), Timeframe, TF_MINUTES, QUALITY_FLAGS; units `Pts Prem Inr R Bps` (float subclasses, `UnitMismatch` on mixed +/-)
- `nifty.timeutil`: `Calendar.load(path=None)` (default `<repo>/data/calendar.yml`), `is_session_day`, `session_bounds(d)->(open,close) UTC`, `session_date(ts)`, `is_verified`; `IST`, `to_ist`, `utcnow`
- `nifty.marketdata.validation.validate_bars(bars, cal)->(accepted, ValidationReport)`; `.resample.resample(bars, tf, cal)`; `.importer.parse_csv|parse_json|parse_kite_candles|parse_file` (`ImportRejected`); `.base` (`MarketDataProvider` Protocol, `ErrorCode`, `ProviderError`, `Tick`); `.providers.csv_replay.CsvReplayProvider(path, instrument, tz, calendar)`
- `nifty.db.bars`: `upsert_bars(conn,bars)->UpsertResult{inserted,revised,noop}`, `read_bars(conn,iid,tf,start,end,last_n)`, `create_snapshot(conn,iid,tf,from,to)->Snapshot`; `nifty.db.instruments`: `upsert_instrument`, `find_by_symbol`
- CLI: `import-csv PATH --symbol S --tick-size X [--tz] [--dry-run]`, `bars --symbol --tf --n` (`make bars SYM= TF= N=`), `snapshot --symbol --from --to [--tf]` (inclusive session dates)
- Tables (rev 0002): `instruments`, `bars` (hypertable 30d chunks, PK instrument_id,timeframe,bar_start_utc,revision; doubles, no rounding), `datasets`, `calendar_days` (created, no loader yet)
- Snapshot rule: latest revision per bar_start in [from,to); canonical row = `start_utc_iso|rev|o|h|l|c|v|volume_kind` with `repr()` floats; sha256 of rows joined by newline; `snapshot_id = snap_ + sha256(iid|tf|from|to|sha)[:16]`; excludes received_at_utc and quality_flags
- Upsert rule: identical (o,h,l,c,v,volume_kind) to ANY stored revision = no-op; otherwise new revision = max+1
- DB-test rule: marker `db`; run on `nifty_test` on the server in `DATABASE_URL` (repo-root `.env`), never the dev DB; migrated through a passed connection (alembic `config.attributes["connection"]`) and rolled back after each test; skipped only when the server is unreachable, an auth failure fails.
- DB tests: `tests/conftest.py` fixtures `test_db_url` / `migrated_url` (alembic via connection) / `db_conn` (rolled back per test)
- Make targets implemented: up down ps logs check test migrate db-q bars init-env hash-password api-types. Stubs (exit 2): parity bench e2e. `bars` wired (C01). `db-q` falls back to local psql when no compose db is running.
- Ports: api 8000, web 8080, db 5432 / redis 6379 (127.0.0.1 only). Images: timescale/timescaledb:2.17.2-pg16, redis:7.4.1-alpine, python:3.14-slim, node:22-alpine, nginx:1.27-alpine (UNVERIFIED pulls)
- Local py: `Makefile.local` (gitignored) PY/PIP = `/home/balaj/projects/practicalenv/bin/{python,pip}`

## Deviations (spec → actual, why)
- Unit types are float subclasses, not `typing.NewType` (NewType cannot raise `UnitMismatch`). Not used on the per-bar hot path (D27).
- `calendar_unverified` is reported on `ValidationReport`, not stored per bar (it would change bar identity when the calendar is edited). Per-bar flags stored: `gap_before`, `volume_absent`, `partial_bucket` (resample only).
- Validation adds exclusion reasons `non_finite bad_ohlc bad_volume off_session non_session_day` beside `off_grid`; reports `out_of_order` (sorted, never silent). Gaps are interior only; session start/end shortfalls appear in `sessions`.
- `resample`: `partial_bucket` = bucket reaches outside the session's data extent or past the session close; `gap_before` = missing slots inside the extent. Accepts any dividing input tf; 1d->1d is identity.
- `ruff` per-file ignore E501 for alembic/ and tests/; mypy `ignore_missing_imports` for yaml (no types-PyYAML dep).
- `/readyz` head revision now derived from `backend/alembic` via ScriptDirectory.
- AGENTS.md's venv path is a stale Mac path; real local venv is `/home/balaj/projects/practicalenv` (user-confirmed). Only in Makefile.local.
- `setup-reference.sh` can't copy (Mac source path); `reference/` was already populated, `sha256sum -c SHA256SUMS` all OK. Script left unchanged.
- No Docker on this WSL host (user: continue without). Docker-dependent acceptance deferred, see Open issues.
- `APP_PASSWORD_HASH` is printed single-quoted (`'scrypt$...'`): compose/dotenv would interpolate `$`. Verified pydantic-settings strips the quotes.
- web: `typescript@5` (not 7): openapi-typescript 7.13 needs the TS 5 compiler API. Single `web/tsconfig.json` so `tsc --noEmit -p` really checks src.
- ruff rules pinned in pyproject (E,F,I,UP,B; B008 ignored for FastAPI Depends). `/healthz` and `/readyz` are at root (not under /api/v1) to match the acceptance curls.

## Open issues / ASKs
- Backend image now mirrors the repo layout (`/app/backend`, `/app/data`, editable install) so `parents[3]` paths resolve; UNVERIFIED until Docker exists.
- Oracle CSV has no data for Tue 2026-11-10 (18 weekdays, 17 sessions). Not added to the calendar (never guess holidays). User: confirm whether it was a market holiday and fill `data/calendar.yml`.
- `calendar_days` table is created but nothing loads `data/calendar.yml` into it yet.
- Deferred (no Docker): `docker compose config -q`, image pulls/tags, `make up`/`down`/`db-q` (db-q is Docker-only; use `psql "${DATABASE_URL/+psycopg/}"`). Compose stack untested.
- `python -m nifty.worker` / `nifty.collector` (compose profiles) have no entrypoints until C04/C08.
- AGENTS.md still names the Mac venv; user may want to update it.

## Facts discovered (environment, data, Kite; keep short)
- Native DB verified 2026-11-23: `make migrate` -> rev 0001, timescaledb ext + prefs present, `nifty_test` DB test passes, live /healthz 200, /readyz 200, /auth/me 401 unauth. Needed PGDG repo for pg 18.7 (Ubuntu has 18.6; Timescale 2.32 needs >=18.7). Role is SUPERUSER (dev only).
- WSL Ubuntu 26.04, Python 3.14.4, node 22.22, npm 9.2; apt offers postgresql 18, redis 8.0; timescaledb needs Timescale's apt repo.
- Resolved deps (3.14 wheels all available): fastapi 0.165, sqlalchemy 2.1.9, alembic 1.20, pydantic 2.14, psycopg 3.3.9, numpy 2.5, pandas 3.1.
- `make check` green (C01): ruff, format, mypy strict, pytest 51 incl. DB tests, tsc, vitest. Oracle import verified: 5997/5996/1 off_grid/17 sessions/3 gaps/absent; 2nd import 0 rows; snapshot id stable (snap_d58a5e9581f9cfe6 for 2026-10-22..2026-11-16 1m).
