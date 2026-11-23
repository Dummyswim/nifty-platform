# C01 · Data core
effort: med · deps: C00 · reads: `docs/spec/01-contracts.md` (units, Instrument, Bar) · `docs/spec/02-data-time.md` (all) · `docs/spec/05-backend.md` (Layout, Provider interface, Tables) · `docs/SOURCES.md` (quirks)
pine: — · tools: bash (`make test`, `make db-q`, `make bars`) · pandas one-liners for summaries only (never print rows) · create/edit

**Goal.** Trustworthy bars: contracts, time/session/resample, validation, importer, snapshots, storage, CSV provider. The oracle CSV imports with exactly the documented quirks reported.

**Do**
1. `nifty.contracts`: unit NewTypes + `UnitMismatch`, `Timeframe`, `Instrument`, `Bar`, `ValidationReport` (spec/01, spec/02). Event, Overlay, Trade and Engine contracts wait for C02.
2. `nifty.timeutil`: IST/UTC helpers, `Calendar` loaded from `data/calendar.yml` (ship an example **without** holidays and without `verified_through` ⇒ weekdays + `calendar_unverified`; never invent holidays), session open/close, `session_date(ts)`.
3. `nifty.marketdata.resample` (pure, deterministic): session-anchored 1m → 3m 5m 10m 15m 30m 1h 1d (spec/02). Buckets never straddle sessions; incomplete buckets are still emitted with `partial_bucket` / `gap_before`. A bucket is `finalized` when its last 1m bar is present or a later 1m bar exists; a trailing bucket of a dataset that stops mid-bucket is `finalized=False`.
4. `nifty.marketdata.validation.validate_bars` (pure) per spec/02: off-grid exclusion, OHLC sanity, duplicates (identical dropped; differing ⇒ revision+1), NaN/negative volume rejected, in-session gaps, `volume_kind=absent` when all volume is 0. Returns accepted bars + `ValidationReport`.
5. `nifty.marketdata.importer`: CSV/JSON/Kite-array parsers → Bars. **1m only** (D08): other timeframes are rejected; naive timestamps rejected unless `--tz`; `--tick-size` is required for CSV instruments (never invented; the oracle is 0.05).
6. DB access lives only in `nifty.db.*`. One Alembic revision: `instruments`, `bars` (hypertable; unique `(instrument_id, timeframe, bar_start_utc, revision)`), `datasets`, `calendar_days`. `db/bars.py`: idempotent upsert (same row = no-op; differing = new revision), range reads, `create_snapshot()` (`snapshot_id` = sha256 of canonical rows, spec/02).
7. `marketdata/base.py` (`MarketDataProvider`, error taxonomy) and `providers/csv_replay.py` (`list_instruments`, `historical`, `status`; `stream` raises `NotImplementedError` until C08).
8. CLI (each ≤20 lines of output): `import-csv PATH --symbol "NIFTY 50" --tick-size 0.05 [--tz]` · `bars --symbol --tf --n` (wire `make bars`) · `snapshot --symbol --from --to`.
9. Tests: unit (validation edge cases; resample on a 14:50 partial session and on a session missing 14:49) · hypothesis on random 1m series (OHLC aggregation, volume sum, no bucket crosses a session, resampling its own output grid is idempotent) · `db` tests (upsert idempotency, revision, snapshot hash stable across runs).

**Acceptance (oracle).** `python -m nifty.cli import-csv reference/oracle/data/nifty_1m.csv --symbol "NIFTY 50" --tick-size 0.05` reports: rows_in 5997 · accepted 5996 · excluded 1 (`off_grid`, 2026-11-16T14:49:50+05:30) · 17 sessions (first starts 14:50 with 40 bars; last ends 14:48 with 334 bars) · 14:49 missing on 2026-10-26, 2026-11-02, 2026-11-09 · `volume_kind=absent`. A second import adds 0 rows; two snapshots of the same range hash identically; `make bars SYM="NIFTY 50" TF=5m N=3` works; `make check` green (DB tests skip with a note if docker=no).
**Record in STATE:** resample/validation/importer/db/provider APIs, CLI commands, tables, snapshot rule, calendar file path, DB-test rule.
