# Evidence (webapp success criteria, 2026-11-24)

Final `make check`: ruff, ruff format, mypy (strict), pytest **382 passed, 1 skipped** (1 intermittent failure seen once in
`test_options_api::test_contract_bars_...`, not reproduced in 3 later full runs), tsc, vitest **48 passed**. `make e2e` green
(chart, TF switch, drawings, replay, backtest/audit, Balu, Options, Research, Analytics, Settings; live demo). `make bench`
(SYNTHETIC 100k bars): NVS 96k 1m bars/s batch, 50k incremental; Balu 28k batch, 22k incremental; peak RSS 379 MB.

| Criterion | Evidence | Result |
|---|---|---|
| NIFTY loads on a 1m chart at startup | e2e `smoke.spec.ts`: `data-tf=1m`, `data-bars > 1000` on first load | verified (oracle data) |
| VWAP strategy overlays automatically | e2e: NVS ready, 15 entry markers, VWAP in panel | verified |
| Dynamic ITM/ATM/OTM option loading | `test_options_api`, e2e Options (ITM CE = ATM-2 steps, PE mirrored) on SYNTHETIC chain; strikes/expiries derived from master | verified on synthetic fixture; **not verified: real Kite option chain** |
| Historical tick storage | `ticks` hypertable + collector tests (`test_live_pipeline`, window recorder) | verified offline; **not verified: live Kite WS ticks** |
| Strategy replay | e2e: jump, step forward, entry markers revealed up to the cursor, exit replay | verified |
| TradingView-like UX | e2e chart/drawings/indicator panel/replay/audit | verified functionally; no side-by-side visual review |
| Extensible architecture | one Engine/Bar/Event/Overlay contract; 3 engines registered; `PORTING.md`; D14 property tests | verified |
| Read-only, no orders (D19) | `test_no_order_endpoints`, Kite client allowlist tests | verified |
| Security (C15) | `tests/test_security.py`: all routes need the cookie except `/healthz`, `/readyz`, Kite redirect; WS closes without cookie; no wildcard CORS; no schema pages; compose ports loopback. `git grep` for secrets: only a `getpass` call and a test dummy; `.env` untracked; cookie flags + redaction tests in `test_auth`, `test_kite_client` | verified |
| Reproducible builds | `backend/requirements.lock` (54 pins, `make lock`), Dockerfile uses `-c`, web `npm ci` + `package-lock.json` | lockfile generated; **not verified: Docker build (no Docker)** |
| Compose stack | `docker compose config/build/up` | **not verified: Docker not installed on host** |

## Parity per engine
| Engine | Golden TradingView data | Status |
|---|---|---|
| `pine.nvs_scalper` | missing (`fixtures/tv_golden/nvs/` empty) | oracle (twin) match: 15/15 entries, 14/15 exits; `make parity` says `golden missing` |
| `pine.balu_zone` | missing (`fixtures/tv_golden/balu/` empty) | unit/step tests and D14 properties only |
| `research.distance_entry_v1` | n/a (not a Pine port) | oracle counts + D14 properties |

## Remaining gaps and risks
Golden exports pending (user); Kite live WS, option recording, backfill unverified in market hours; holiday 2026-11-10 unconfirmed;
`anchor_cross_ema_order` is our interpretation; Docker untested; research verdicts need >= 60 sessions (oracle has 17: `inconclusive`).
