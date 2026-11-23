# STATE (≤150 lines; prune every session)

next_chunk: C01
last_update: 2026-11-23 (C00)
env: provider=kite · docker=no · db=native(WSL pg18.7+timescaledb 2.32.1, redis 8.0) · golden_tv=none · kite_creds=none

## Chunks (status: pending | partial | done; partial needs resume_at)
| id | status | notes |
|----|--------|-------|
| C00 | done | scaffold, compose, make tools |
| C01 | pending | data core, CSV replay |
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
- `nifty.api.main:create_app` (factory); root `/healthz`, `/readyz` (503 if DB down or alembic != `HEAD_REVISION` in api/main.py: bump each migration); `/api/v1/auth/login|logout|me`; `nifty.api.auth.require_user` guards every later route
- `nifty.security`: scrypt `hash_password/verify_password`, `sign_session/read_session`
- Make targets implemented: up down ps logs check test migrate db-q init-env hash-password api-types. Stubs (exit 2): parity bench e2e bars
- Ports: api 8000, web 8080, db 5432 / redis 6379 (127.0.0.1 only). Images: timescale/timescaledb:2.17.2-pg16, redis:7.4.1-alpine, python:3.14-slim, node:22-alpine, nginx:1.27-alpine (UNVERIFIED pulls)
- Test DB rule: marker `db`; admin = `DATABASE_URL` (repo-root `.env`, read from any cwd via `nifty.config.ENV_FILE`) with db swapped to `postgres`; creates/uses `nifty_test`, never the dev DB. Skips only if unreachable; auth failure fails loudly.
- Local py: `Makefile.local` (gitignored) PY/PIP = `/home/balaj/projects/practicalenv/bin/{python,pip}`

## Deviations (spec → actual, why)
- AGENTS.md's venv path is a stale Mac path; real local venv is `/home/balaj/projects/practicalenv` (user-confirmed). Only in Makefile.local.
- `setup-reference.sh` can't copy (Mac source path); `reference/` was already populated, `sha256sum -c SHA256SUMS` all OK. Script left unchanged.
- No Docker on this WSL host (user: continue without). Docker-dependent acceptance deferred, see Open issues.
- `APP_PASSWORD_HASH` is printed single-quoted (`'scrypt$...'`): compose/dotenv would interpolate `$`. Verified pydantic-settings strips the quotes.
- web: `typescript@5` (not 7): openapi-typescript 7.13 needs the TS 5 compiler API. Single `web/tsconfig.json` so `tsc --noEmit -p` really checks src.
- ruff rules pinned in pyproject (E,F,I,UP,B; B008 ignored for FastAPI Depends). `/healthz` and `/readyz` are at root (not under /api/v1) to match the acceptance curls.

## Open issues / ASKs
- Deferred (no Docker): `docker compose config -q`, image pulls/tags, `make up`/`down`/`db-q` (db-q is Docker-only; use `psql "${DATABASE_URL/+psycopg/}"`). Compose stack untested.
- `python -m nifty.worker` / `nifty.collector` (compose profiles) have no entrypoints until C04/C08.
- AGENTS.md still names the Mac venv; user may want to update it.

## Facts discovered (environment, data, Kite; keep short)
- Native DB verified 2026-11-23: `make migrate` -> rev 0001, timescaledb ext + prefs present, `nifty_test` DB test passes, live /healthz 200, /readyz 200, /auth/me 401 unauth. Needed PGDG repo for pg 18.7 (Ubuntu has 18.6; Timescale 2.32 needs >=18.7). Role is SUPERUSER (dev only).
- WSL Ubuntu 26.04, Python 3.14.4, node 22.22, npm 9.2; apt offers postgresql 18, redis 8.0; timescaledb needs Timescale's apt repo.
- Resolved deps (3.14 wheels all available): fastapi 0.165, sqlalchemy 2.1.9, alembic 1.20, pydantic 2.14, psycopg 3.3.9, numpy 2.5, pandas 3.1.
- `make check` green: ruff, format, mypy strict, pytest (12 pass, 1 DB skip), tsc, vitest (2).
