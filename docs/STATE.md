# STATE (≤150 lines; prune every session)

next_chunk: C04
last_update: 2026-11-23 (C03)
env: provider=kite · docker=no · db=native(WSL pg18.7+timescaledb 2.32.1, redis 8.0) · golden_tv=none · kite_creds=none

## Chunks (status: pending | partial | done; partial needs resume_at)
| id | status | notes |
|----|--------|-------|
| C00 | done | scaffold, compose, make tools |
| C01 | done | data core, CSV replay |
| C02 | done | engine framework, pinekit, broker emulator |
| C03 | done | NVS port, parity harness |
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
- Engines (C02). Register: `from nifty.engines.base import register_engine`; call `register_engine(MyEngine, ready=bool)` at import time of the engine module and add that module to `BUILTIN_ENGINE_MODULES` (loaded by `load_builtin_engines()`). `list_engines()` hides `ready=False`; `get_engine(id, allow_unready=False)`. Engine class attrs: `id version default_timeframe Params plots warmup_bars`; methods `on_bar on_provisional snapshot restore panel`; `Params` subclasses `EngineParams` (extra=forbid; `ui: UiParams` subclass excluded from config_hash)
- Runner (`nifty.engines.runner`): `run_batch(engine_id, params, bars_1m, timeframe=None, *, instrument=None, calendar=None, source_id="batch", allow_unready=False, proxy_volume_1m=None) -> RunResult`; `run_incremental(engine_id, params, bars_1m, timeframe=None, *, ..., provisional=False, restart_after=None)`; `run_with_restart(engine_id, params, bars_1m, timeframe=None, *, cut, **kw)` (snapshot after `cut` chart bars -> `json.dumps(allow_nan=False)` round trip -> new engine+ctx -> `restore`). `RunResult{bars, plots[(bar_start, {name: float|None})], events[EngineEvent], overlays[OverlayElement], trades, panel, provisional[...], config_hash, source_id,...}`. Runner stamps event envelope (engine_id/version/config_hash/instrument/source/tf/times), `seq` per (bar_start, event_type), `available_at_utc = bar_end` (provisional: that 1m bar's end), NaN -> None in plots, event payloads, panel, overlay p0/p1/style/meta and trade fields (a NaN in a REQUIRED trade float raises ValueError). Event id = uuid5(`EVENT_NAMESPACE`=6b0f1c52-3f3e-5a4e-9d57-7a1e0c2b8a10, `engine|config_hash|instrument|tf|bar_start_iso|type|seq[|provisional]`)
- `EngineContext(instrument, timeframe, calendar, proxy_volume_1m=None)`: `mintick` (ConfigError if tick_size None), `provisional` flag, `append_1m` (runner only), `prior_day(bar)->PriorDay{date,high,low,close}|None`, `htf(bar,res)->HtfStep{new_bar, completed}`, `sub_bars(bar,res)->list[Bar]` (ConfigError unless res < chart tf and divides it), `proxy_volume(bar)->float|None`
- pinekit (`import nifty.engines.pinekit as pk`): `NaN isna nz pmax pmin (also pk.max/pk.min) Series enc dec` · stateful `Sma Sum Highest Lowest Stdev Ema(len, seed='first'|'sma') Rma Tr Atr AtrSess Rsi Change Crossover Crossunder PivotHigh PivotLow(left,right,pivot_ties='default'|'strict')` each `update(...)`, `state()`, `load()` (JSON-safe) · `round_to_mintick(x, mintick)` · session helpers `bar_minutes_ist is_new_session(bar, prev, cal) is_last_bar_of_session(bar, cal) bucket_start timeframe_change(bar, prev, res, cal)`
- Execution: `resolve_barriers(side, entry_px, stop_px, target_px, bars, max_hold_bars, mode, cost_pts=0.0) -> Resolution{exit_idx, exit_px, reason TARGET|STOP|TIME, flags, mae_pts, mfe_pts, bars_held, gross_pts, cost_pts, net_pts}`; `step_bar(...)`. `BrokerEmulator(engine_id, instrument_id, qty=1, commission_pct=0)`: `on_bar(bar)->[TradeRecord]` (call BEFORE the script), `entry(side, signal_bar_start, reason)`, `close(reason, immediately=False)`, `close_all(...)`, `exit(stop=None, limit=None)`, `.position` (script-visible), `.actual_position`
- DB (rev 0003): tables `engine_configs engine_runs plot_points events overlay_elements` (events/overlays carry `ord` = emission order). `nifty.db.runs`: `persist_run(conn, RunResult)->(run_id, created)`, `find_run`, `load_plots`, `load_events(conn, run_id, available_by=None)`, `load_overlays(...)`. Run key = sha256(engine|version|config_hash|source_id|timeframe). `run-engine` and `snapshot` share `nifty.cli.session_range` (inclusive session dates; omitted => first/last stored bar's session), so they produce the same snapshot_id
- CLI: `run-engine --engine ID --symbol S [--timeframe] [--from --to] [--params JSON|@file] [--no-persist] [--allow-unready]` (function `nifty.cli.run_engine(conn, ...)`). No production engine exists yet, so it cannot be run by hand until C03; covered by DB tests with `test.sma_cross`
- NVS (C03): engine `pine.nvs_scalper` v1, `nifty.engines.nvs` (`NvsScalper`, `NvsParams` in `params.py`; registered `ready=True`, listed in `BUILTIN_ENGINE_MODULES`). Doc `docs/engines/nvs.md`. Engine owns a `BrokerEmulator` (calls `on_bar` first); emits trades in `EngineOutput.trades`. Emulator gained `state()/load()` (snapshot) and `cancel_entries()`.
- Parity (`nifty.parity`): `tv_io` (`RefTrade`, `load_tv_ohlc_plots`, `tv_bars`, `load_tv_trades`, `load_oracle_trades`, `parse_time`), `compare` (`tier_a(ours_plots, golden{series:{ts:v}}, warmup)`, `tier_bc(trades, ref, tf, px_tol, exit_px_tol)->TierBC{entries_ok, exits_ok, diffs}`), `cli.run_parity(engine, golden, oracle)`; `SERIES` maps TV plot titles -> engine plots per engine (add Balu in C09). CLI `python -m nifty.cli parity --engine ID [--golden DIR] [--oracle PATH]`; `make parity E=<id> [G=dir]`. Golden dir default `fixtures/tv_golden/<engine_id>`, falls back to `.../nvs` (RUNBOOK name).
- Make targets implemented: up down ps logs check test migrate db-q bars parity init-env hash-password api-types. Stubs (exit 2): bench e2e. `bars` wired (C01). `db-q` falls back to local psql when no compose db is running.
- Ports: api 8000, web 8080, db 5432 / redis 6379 (127.0.0.1 only). Images: timescale/timescaledb:2.17.2-pg16, redis:7.4.1-alpine, python:3.14-slim, node:22-alpine, nginx:1.27-alpine (UNVERIFIED pulls)
- Local py: `Makefile.local` (gitignored) PY/PIP = `/home/balaj/projects/practicalenv/bin/{python,pip}`

## Deviations (spec → actual, why)
- C03: Pine L278 `barstate.isconfirmed` (missing from the port map) is honoured: no `signal` while `ctx.provisional`. `run_batch` skips the 1m aux buffer when fed chart-tf bars (TV golden input). `docs/prompts/` (untracked user copy of C03) left alone.
- C03: golden dir `fixtures/tv_golden/<engine_id>` (spec/04) and RUNBOOK's `.../nvs` both accepted. NVS plot `buy/sell_near/far` are always computed (the Pine `showBands` toggle is UI only). `volume_kind=absent` forces TWAP even if a volume value is present. Stop/target overlay lines show the INITIAL levels; BE ratchets are `stop_update` events.
- Chart bars handed to engines carry NO `quality_flags` (partial/gap flags use later data = lookahead and differ batch vs incremental). Engines see `volume_kind` and finalized bars only; flags remain on stored/resampled bars.
- D07 run key includes `timeframe` (config_hash does not cover it). Trades are not persisted in C02 (C04 `trades`).
- Tests live in `backend/tests/unit/{engines,execution,contracts}/`; `make test T=backend/tests/...` strips the `backend/` prefix. Test engine `test.sma_cross` is in `backend/tests/sma_cross_engine.py` (registered only inside tests).
- `prior_day` = previous session present in the data (e.g. Wed 11-11 sees Mon 11-09, no data on 11-10).
- Conservative mode MFE on a STOP bar = 0 (no credit for favourable moves), MAE clipped at the stop; tv mode uses the O-H-L-C path. Tie `(high-open)==(open-low)` => path O-L-H + flag `uncertain_path`.
- `atr_sess` = Wilder ATR where TR resets to high-low on a session's first bar; smoothing stays continuous (spec/07 L14).
- `EngineSpec.cls`/`register_engine` are typed `type[Any]` (mypy cannot express protocol class attributes).
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
- golden_tv=none: NVS golden not exported yet; `make parity` prints `golden missing` for it. Export steps: RUNBOOK §Golden (user to confirm when files exist).
- Golden decides (log result in STATE when C03/C09 compare): `ema_seed` (default 'first'), rsi both-zero (100), `pivot_ties` (default), `round_to_mintick` epsilon.
- Provisional events: the id is the same for every 1m update of one (bar, type, seq) slot, so consumers (C08) must treat a repeated id as 'replace with the latest update'; `available_at_utc` is that update's 1m bar end.
- Provisional plots/events are kept on `RunResult.provisional` only; not persisted.
- Backend image now mirrors the repo layout (`/app/backend`, `/app/data`, editable install) so `parents[3]` paths resolve; UNVERIFIED until Docker exists.
- Oracle CSV has no data for Tue 2026-11-10 (18 weekdays, 17 sessions). Not added to the calendar (never guess holidays). User: confirm whether it was a market holiday and fill `data/calendar.yml`.
- `calendar_days` table is created but nothing loads `data/calendar.yml` into it yet.
- Deferred (no Docker): `docker compose config -q`, image pulls/tags, `make up`/`down`/`db-q` (db-q is Docker-only; use `psql "${DATABASE_URL/+psycopg/}"`). Compose stack untested.
- `python -m nifty.worker` / `nifty.collector` (compose profiles) have no entrypoints until C04/C08.
- AGENTS.md still names the Mac venv; user may want to update it.
- NVS: `anchor_mode=fill_price` is the twin's convention but is not exercised against the oracle (decline rule uses 1.25*maxRisk like the twin; stop stays mintick-rounded).

## Facts discovered (environment, data, Kite; keep short)
- Oracle conventions (twin `vwap_scalper.py`): `entry_ts` = FILL bar start (signal at the previous close); `exit_ts` = bar start of the bar that exited (EOD/SESSION_END stamped at the signalling bar start, emulator stamps bar END); `resample` is session-anchored at 09:15 and KEEPS a trailing partial bucket (we drop it: only finalized bars reach engines; 11-16 14:45 bar, no trade affected). Twin trade prices are fill-anchored and unrounded; Pine anchors to the signal close and rounds to mintick.
- NVS vs oracle (5m, tv, signal_close): entries 15/15, exits 14/15 (11-03 TP fires 2 bars later than twin, target anchoring). `make check` green (20 NVS tests incl. prefix immunity and a golden-file round trip with synthetic TV exports).
- Native DB verified 2026-11-23: `make migrate` -> rev 0001, timescaledb ext + prefs present, `nifty_test` DB test passes, live /healthz 200, /readyz 200, /auth/me 401 unauth. Needed PGDG repo for pg 18.7 (Ubuntu has 18.6; Timescale 2.32 needs >=18.7). Role is SUPERUSER (dev only).
- WSL Ubuntu 26.04, Python 3.14.4, node 22.22, npm 9.2; apt offers postgresql 18, redis 8.0; timescaledb needs Timescale's apt repo.
- Resolved deps (3.14 wheels all available): fastapi 0.165, sqlalchemy 2.1.9, alembic 1.20, pydantic 2.14, psycopg 3.3.9, numpy 2.5, pandas 3.1.
- `make check` green (C02): ruff, format, mypy strict, pytest 130 incl. DB tests (nifty_test), tsc, vitest. Oracle import + snapshot numbers from C01 unchanged. Dev DB migrated to 0003.
