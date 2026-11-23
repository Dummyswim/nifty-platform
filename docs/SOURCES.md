# Sources (pinned)

Copied into `reference/` by `bash scripts/setup-reference.sh`, which verifies `reference/SHA256SUMS`. Hash mismatch ⇒ STOP and ask: the line refs in `docs/pine/*` and this pack are stale.

| reference/ path | lines | sha256 (first 12) | role |
|---|---|---|---|
| pine/Nifty_VWAP_Spread_Scalper.pine | 358 | 2b4318a417c0 | NVS strategy (Pine v6) → C03 |
| pine/Balu_Zone_Scalper_v2.pine | 895 | 4e3ee43c12f1 | Balu v2.2 indicator → C09–C11 |
| src/webapp-prompt.md | 314 | 93f538673191 | platform requirements (cite line ranges only) |
| src/research-prompt.md | 412 | 643060a401b6 | research prompt (condensed into `docs/spec/07-research.md`; cite ranges only) |
| oracle/vwap_scalper.py, test_vwap_scalper.py, VWAP_SCALPER.md | 751/326/– | a2a9bdb3…/8be405e6…/ea07d799… | NVS Python twin (ignore its Dhan/Yahoo fetch and live code) |
| oracle/data/nifty_1m.csv | 5,997 rows | fe69c7c1d8ec | NIFTY 1m index bars, 17 sessions, 2026-10-22→11-16, volume = 0 |
| oracle/logs/scalper_trades.csv | 15 trades | 1bd6b7e23b1c | twin's trade list (parity target for C03) |

## Superseded in the original prompts
Dhan → Kite (D01) · `KITE_ACCESS_TOKEN` in `.env` → daily login flow with the token stored encrypted in the DB (D19); only key and secret live in `.env` · "FastAPI or NestJS" → FastAPI (D02) · "Next.js" → Vite SPA (D26) · research §14 milestones → chunks C00–C15 · research §16 handoff → STATE.md + C15.

## nifty_1m.csv quirks (C01 must detect and report them, not hide them)
- First session starts 14:50 IST (40 bars). Last session ends 14:48.
- 14:49 is missing on 2026-10-26, 2026-11-02 and 2026-11-09.
- One off-grid row `2026-11-16T14:49:50+05:30` (appended live quote) → exclude and report.
- Volume is 0 on every row → `volume_kind=absent`; anchor falls back to TWAP.

No oracle exists for Balu. Golden TradingView exports (optional): see `prompts/00-RUNBOOK.md` §Golden.
