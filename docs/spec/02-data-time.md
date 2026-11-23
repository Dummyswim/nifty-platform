# Data & time (modules `nifty.timeutil`, `nifty.marketdata`)

## Time (D21)
- Store `timestamptz` UTC; convert to Asia/Kolkata only at API edges, UI and session logic.
- Session 09:15–15:30 IST: 1m bars start 09:15 … 15:29. `bar_start` inclusive, `bar_end` exclusive.
- Session-anchored resampling (D08): 5m buckets start 09:15, 09:20 …; 1h buckets 09:15, 10:15 … with a last partial 15:15–15:30 (flag `partial_bucket`); 1D = one bar per session. Buckets never straddle sessions. A bucket finalizes when its last 1m bar (or the session end) arrives; missing 1m bars inside it ⇒ flag `gap_before`/`stale`, still emit.
- Calendar (D09): `data/calendar.yml` = `holidays: [YYYY-MM-DD…]`, `special_sessions: [{date, open, close}]`, `verified_through: YYYY-MM-DD` → versioned `calendar_days`. No file or dates beyond `verified_through` ⇒ weekdays only + `calendar_unverified`.

## Validation (importer and collector share it; never silently repair)
Monotonic · grid-aligned to the timeframe (off-grid rows excluded and reported) · OHLC sanity (`low ≤ min(o,c)`, `high ≥ max(o,c)`, finite) · duplicates (identical ⇒ drop; differing ⇒ new `revision`, keep both) · NaN or negative volume rejected · in-session gaps detected · volume all 0 ⇒ `volume_kind=absent` (`volume_absent`).
`ValidationReport{rows_in, rows_ok, excluded[{ts, reason}], gaps[{day, from, to, missing}], duplicates, sessions[{date, first, last, n}]}`.

## Snapshots
`snapshot_id` identifies (instrument, timeframe, from, to, revision set) plus `sha256` of canonical rows (sorted, fixed float repr). Backtests and jobs reference `snapshot_id`. Late revisions (EOD reconcile) add rows with `revision+1`; as-known live events are never rewritten.

## Ticks
Hypertable `ticks(instrument_id, ts, last_price, volume, oi, bid, ask, bid_qty, ask_qty, received_at)`. Compression policy after ~7 days. No automatic deletes (retain indefinitely unless the user purges).

## Import formats
- CSV `timestamp,open,high,low,close,volume` (ISO-8601 with offset). Naive timestamps are rejected unless `--tz Asia/Kolkata`.
- JSON `[{timestamp, open, high, low, close, volume}]`.
- Kite candle arrays `[ts, o, h, l, c, v(, oi)]` with offsets like `+0530` (parse with `%z`).

## Quirks to detect and report (oracle `reference/oracle/data/nifty_1m.csv`, see `docs/SOURCES.md`)
Partial first session (starts 14:50), session ending 14:48, three sessions missing 14:49, one off-grid row `2026-11-16T14:49:50+05:30` (an appended live quote), volume 0 on every row.
