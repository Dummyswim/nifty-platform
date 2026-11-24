# Live session: start, watch, review

## Before the open (08:45–09:10 IST)
1. `make start` (API :8000, worker, web :8080). Open http://127.0.0.1:8080 and log in.
2. **Settings -> Connect Kite** (the token expired at 06:00 IST) -> approve at Zerodha. Status must read connected.
   Settings -> Refresh instruments (daily master). Optional: `make kite-smoke` in a second terminal.
3. **Chart -> Indicators**: switch on the engines you want recorded live (`pine.nvs_scalper` is on by default,
   `pine.balu_zone`, `research.distance_entry_v1` are off). The collector reads this list when it starts.
   Also set Settings -> Options -> risk-free rate if you want Greeks, and check the option recording window.
4. Stop with Ctrl-C and restart as `make start ARGS=--live` (API + worker + web + live collector, one terminal).
5. Second terminal: `make session-monitor` (samples health, ticks, CPU and memory every 15 s into
   `logs/session/<date>/monitor.jsonl`). Leave it running until after 15:30.
6. Chart -> **Live** on NIFTY 50. Within ~10 s the badge should be `live` and the last candle should move.

## What to watch during the session
- Live badge: `live` good; `stale` (no ticks for a while), `disconnected`, `auth_expired` (reconnect Kite), `down` (collector died).
- The forming 1m candle matches the Kite web/TradingView candle (open/high/low/close within a tick or two); volume for the
  index is n/a (we never invent it).
- At each minute close a new candle appears once, never twice, and engine markers (NVS entries, research labels) only on closed bars.
- Reload the page mid-session: the chart, markers and drawings come back identical (no duplicates, no vanished labels).
- Options page: ATM strike follows spot, chain rows fill with recorded quotes only; `no_quote` shown instead of invented prices.
- Terminal noise: repeated `reconnect`, `bad packet`, `rate limit`/429, or `late tick` lines. A few reconnects are fine; a loop is not.
- Memory of the collector should be flat after the first hour; steadily rising RSS is a leak. Note the time of anything odd.
- Labels are experimental research output (BEARISH INDEX / PUT CANDIDATE, BULLISH mirror), not advice, and nothing is ever ordered.
- Do not restart the collector for a hiccup unless it says `down`; restarts are safe (it back-fills from Kite and rebuilds), but note the time.

## After 15:30 IST
1. Stop the monitor (Ctrl-C). Keep the app running for the next step.
2. (Optional, writes through the revision log) compare live bars with Kite's official candles:
   `cd backend && python -m nifty.cli kite-backfill --from <today> --to <today>` — the output prints how many bars were *revised*;
   revised > 0 means a live bar differed from Kite's (record how many and by how much in `bars` revisions).
3. `make session-report` (add `ARGS="--date 2026-11-24"` for another day). It writes `logs/session/<date>/`:
   - `report.md`: bars stored vs 375 expected and gaps; tick count, longest gaps, exchange->received latency p50/p95;
     live events per engine with availability lag after bar close; **live vs batch rerun** (events must match, D14);
     trades each engine suggested; option contracts recorded; API/collector/CPU/RSS summary.
   - `events.csv`, `trades.csv`, `latency.csv`.
4. Backtests page: run `pine.nvs_scalper` on today's data and open the audit for each trade; Research page: run on a snapshot
   (verdicts stay `inconclusive` below 60 sessions; one day only gives labels to eyeball).
5. `make backup` (Docker) or `pg_dump` your native DB, then send me `report.md` plus anything odd you noted (time + what you saw).

## How I judge the session
Pass = no missing bars after back-fill, p95 tick latency well under a second, no unexplained reconnect loop, live == batch events,
stable memory, every NVS/research marker on the chart traceable to a row in `events.csv`. Anything else becomes a ticket.
