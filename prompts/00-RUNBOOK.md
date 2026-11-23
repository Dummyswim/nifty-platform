# RUNBOOK (for you; agents never load this except §Golden)

Pack = `AGENTS.md` (always-on rules + tool policy) · `docs/` (decisions, contracts, specs, Pine port maps, `STATE.md` ledger) · `prompts/C00…C15` (one chunk per fresh session). One constant driver prompt runs them all. Nothing else to paste.

## 0. One-time setup
1. Open **`nifty-platform/`** as the project, not `finance/` (it holds unrelated personal files).
2. `bash scripts/setup-reference.sh`: copies the two Pine scripts, the two original prompts and the NVS oracle from `~/Downloads/pineColl` into `reference/` and verifies SHA-256 pins (`PINE_SRC=/path` overrides). A mismatch means the line refs are stale: stop.
3. Tools: Docker (or Colima), Node ≥ 20, the local venv named in `AGENTS.md`, a browser tool for UI chunks (Copilot's browser canvas or Playwright MCP). Policy and make targets: `docs/TOOLS.md`. Never attach a broker or order-capable MCP.
4. Kite (needed from C07; you can build offline first): at developers.kite.trade create an app with type **Connect** (Personal has no historical or WebSocket data), your own Zerodha client ID, Redirect URL exactly `http://127.0.0.1:8000/api/v1/kite/callback` (Kite sends `request_token` to this URL, so the bare `http://127.0.0.1:8000` fails), Postback URL **empty** (it only reports orders placed with the app's key; this app places none, and it needs a public HTTPS URL) and any description. Put the key and secret in `.env` yourself, never in chat. Open the app only at `http://127.0.0.1:8080`, never `localhost` (the login cookie is per host). On a remote server, SSH-tunnel ports 8000 and 8080 so the same URLs work. You log in to Kite once per trading day (Settings → Connect Kite).
5. After C00: `make init-env`, then `make hash-password` (prompts for your login password) and paste the printed `APP_PASSWORD_HASH=…` line into `.env`.

## 1. Run loop
New session per chunk, then `/next` (Copilot: `.github/prompts/next.prompt.md`; Claude Code: `.claude/commands/next.md`, optional arg `C03`). Without slash commands paste:

```text
Read `AGENTS.md` and `docs/STATE.md`. Then open only `prompts/<next_chunk>-*.md` (the chunk named by `next_chunk` in STATE.md) and the files it lists, nothing else. Execute it, run its acceptance commands until green, update `docs/STATE.md`, reply in ≤8 lines (done / deviations / blockers / next_chunk), and STOP. Ask me (question tool) only for missing preconditions, spec conflicts, or steps marked ASK; otherwise decide, log it under Deviations, and continue.
```

- Read the ≤8-line reply, then start a fresh session. Never request two chunks in one session.
- `partial` in STATE: run the same command again; it resumes at `resume_at`.
- Effort → model tier: `high` strongest model and reasoning · `med` standard · `low` fast model.
- Reorder only by editing `next_chunk` in `docs/STATE.md` to a chunk whose deps are done. No parallel sessions (one ledger).
- MVP after C06: NVS on the chart, replay, backtests, audit, analytics on CSV data (local tag `mvp-nvs`).

## 2. Run order
Tokens (K, o200k) = static context per session: AGENTS + shim + driver + STATE (grows) + chunk + listed specs + cited Pine/prompt ranges. Code read or written and tool output are extra.

| Chunk | What | Effort | Deps | Ctx K | You provide |
|---|---|---|---|---|---|
| C00 | scaffold, compose, make tools | low | – | 6.9 | Docker, Node; then init-env + hash-password |
| C01 | data core, CSV replay | med | C00 | 6.7 | – |
| C02 | engine framework, pinekit, broker emulator | high | C01 | 8.3 | – |
| C03 | NVS port + parity harness | high | C02 | 13.5 | optional NVS golden (§Golden) |
| C04 | jobs, backtests, audit, analytics, export | med | C03 | 6.3 | – |
| C05 | UI chart core | low | C01 | 5.5 | OK to download Chromium for Playwright |
| C06 | UI indicators, replay, backtest pages (MVP) | med | C04, C05 | 6.7 | – |
| C07 | Kite REST, instrument master, historical | med | C01, C05 | 7.1 | key/secret in `.env`, or build offline; you run `make kite-smoke` |
| C08 | Kite live collector, live runner, WebSocket | med | C06, C07 | 7.1 | Kite login in market hours to see live |
| C09 | Balu 1: params, levels, Golden/Moving line | high | C03 | 15.2 | – |
| C10 | Balu 2: zones, levels, location, pressure, sweeps | high | C09 | 11.4 | – |
| C11 | Balu 3: path history, panel, alerts | high | C10 | 9.7 | Balu golden export (§Golden) |
| C12 | options dashboard, CE/PE paper mapping | med | C06, C08 | 6.5 | risk-free rate `r` in Settings for Greeks |
| C13 | research engine | high | C03 | 8.5 | answers to product questions on armed-resumption |
| C14 | research runs, statistics, verdict, UI | high | C13, C06 | 9.1 | – |
| C15 | hardening, lockfiles, handoff | low | all | 6.9 | – |

Total ≈ 135K across 16 sessions. Loading the four source files into every session would cost ≈ 27K × 16 ≈ 430K. The whole pack is ≈ 39K on disk; no session loads more than ~15K of it.

## Golden (TradingView exports; optional, the only true Pine parity check)
Parity tiers print `golden missing` and skip until these exist. Export availability depends on your TradingView plan. Chart symbol NIFTY 50, timezone = Exchange (Asia/Kolkata).
- **NVS** (any time after C03): chart 5m, add `Nifty_VWAP_Spread_Scalper` with default inputs. Strategy Tester → List of trades → export to `fixtures/tv_golden/nvs/trades.csv`. Chart menu → Export chart data (strategy plots visible) → `fixtures/tv_golden/nvs/ohlc_plots.csv`. Then run `make parity E=pine.nvs_scalper` and tell the next session the files exist (it updates `golden_tv` in STATE).
- **Balu** (after C11): copy `Balu_Zone_Scalper_v2.pine`, append the lines from `fixtures/tv_golden/BALU_DEBUG_PLOTS.pine.txt` (≤ 64 plots in total), proxy volume OFF, chart 5m. Export chart data → `fixtures/tv_golden/balu/ohlc_plots.csv`. If a debug series is missing from the export, switch its plot to `display=display.all`. The first session may differ on prior-day values; that is flagged, not a bug. Then `make parity E=pine.balu_zone`.

## 3. Coverage matrix
| Original requirement | Where |
|---|---|
| Webapp: Deployment, auth | C00 · C15 · D03 D17 D22 |
| Webapp: Technology preferences | D02 D03 D13 D26 · C00 |
| Webapp: Market data (now Kite) | C01 CSV · C07 REST · C08 live · D01 |
| Webapp: Charting | C05 · C06 |
| Webapp: Options dashboard | C12 |
| Webapp: Indicator engine (Balu, NVS) | C02 · C03 NVS · C06 UI · C09–C11 Balu |
| Webapp: Backtesting · Audit · Analytics | C04 · C06 · C12 |
| Webapp: Real-time | C08 |
| Webapp: Deliverables, success criteria | C15 |
| Research §1 | AGENTS.md flow · `docs/SOURCES.md` |
| Research §2 §3 §6 §7 §9 | `docs/spec/07-research.md` · C13 · C14 |
| Research §4 | D02 D03 · `docs/spec/05-backend.md` |
| Research §5 | C01 · C07 |
| Research §8 | C02 · C13 |
| Research §10 | C12 · C13 |
| Research §11 §12 | C04 · C08 · C14 · C06 |
| Research §13 §15 §16 | C15 and each chunk's acceptance |
| Research §14 | superseded by the chunk list |
| Pine NVS · Balu | C03 · C09–C11 |
| "Tools for the model" | `AGENTS.md` Tools · `docs/TOOLS.md` · each chunk's `tools:` line |

## 4. Decisions you can flip
Edit `docs/spec/00-decisions.md` before the chunk that uses it and log the change in STATE. Likely ones: D02 FastAPI · D26 Vite SPA instead of Next.js · D06 default fill modes · D22 Docker Python 3.14 (fallback 3.13) · D28 own thin Kite client instead of the SDK. D01 (Kite only) is user-confirmed; another provider needs a new adapter and chunk. Strike-type offsets, option window, staleness and `r` are prefs (no code change).

## 5. STATE hygiene
`docs/STATE.md` stays ≤ 150 lines; each session prunes it. If it grows, tell the next session to prune before starting. Commits are local only (`Cxx: <title>`), never pushed, never `.env`.

## 6. Known limits
- Kite lists only live option contracts (expired history assumed absent; C07 verifies): recording from C08 onward is the only source for option backtests (D12). Leave the collector running in market hours.
- Index spot has no volume: anchor = TWAP, labelled. Balu proxy volume needs the front-month future.
- The research anchor-crossover definition is our interpretation (logged in STATE). With fewer than 60 sessions the verdict is `inconclusive`; the oracle has 17.
- NSE holidays are yours to maintain in `data/calendar.yml`; otherwise `calendar_unverified`.
- Greeks are computed locally (`computed`) and stay `n/a` until you set `r`.
