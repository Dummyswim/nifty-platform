# NIFTY Platform — agent rules (always loaded)

Self-hosted TradingView-like NIFTY options research app: Python quant core + FastAPI + Postgres/Timescale + Redis + React/TS. Data: Zerodha Kite (read-only) or CSV replay. **No order placement, ever.** Built chunk by chunk from `prompts/`.

## Every session
1. Read this file and `docs/STATE.md`.
2. Open only `prompts/<next_chunk>-*.md` and the files it lists. Never load whole files from `reference/` (prompts, Pine, oracle); read only the line ranges a chunk cites.
3. Do the chunk. Run its acceptance commands until green.
4. Update `docs/STATE.md` (status, interfaces, deviations, open issues, `next_chunk`), commit locally `Cxx: <title>` (never push; never commit `.env`). Reply ≤8 lines. STOP; never start the next chunk.
5. Missing precondition, spec conflict, or a step marked ASK → ask the user. Otherwise decide, log under Deviations, continue.
6. Can't finish? Leave code green, set `partial` + `resume_at` in STATE, STOP.

## Hard rules
- Authority: Pine source > port maps (`docs/pine/`); `docs/spec/00-decisions.md` (Dnn) beats all other docs; TradingView golden data beats assumptions.
- Kite is the only live/historical provider (D01). Adapter is read-only: never define or call order, GTT or other write endpoints (D19).
- One contract set (`docs/spec/01-contracts.md`): Bar, Event, Engine, Overlay. Engine ids never mix: `pine.nvs_scalper`, `pine.balu_zone`, `research.distance_entry_v1`.
- No lookahead. Engines are incremental `on_bar` on closed bars; signal at bar close, fill at next bar open (`docs/spec/03-execution.md`).
- Never invent prices, Greeks, probabilities, holidays, expiries, lot sizes or strike steps. Derive from data or label `computed`/`proxy`/`n/a`.
- UTC internally, IST at the edges. Unit suffixes `_pts/_inr/_prem/_r`; never mix.
- Secrets live only in `.env`: never read, print, log or commit it (read `.env.example`). No network in tests.
- Smallest diff that meets the chunk. No unrelated refactors, speculative features, or dependencies the chunk doesn't list. Comment only non-obvious code.
- Local dev Python (this machine only): `/Users/bchavdi/jnpr-tasks/practicalenv/venv/bin/python` and its `pip`. It is a shared venv: never `pip install -U` existing packages; run `pip install --dry-run` first and ASK if it would change an installed package. Never install globally. Docker images use their own env.
- Work only inside this folder.

## Tools (details: `docs/TOOLS.md`)
- Dedicated tools beat shell: view/Read (ranges), grep/Grep, glob/Glob, edit/Edit, create/Write. Shell only runs programs (`make`, `docker`, `pytest`, `npm`).
- Parallelize independent calls in one turn; batch edits per file; never re-read what you just wrote.
- Search first, then read ranges. Cap output (`-q`, `--tail 50`, `| head -40`, SQL `LIMIT`).
- Verify through project tools only: `make check`, `make test T=…`, `make parity E=…`, `make e2e`, `make db-q Q=…`. They print ≤40 lines.
- Send noisy/long runs (full suite, image builds) to a sub-agent/background task; consume its summary only.
- Web only for URLs a chunk names; distil facts into `docs/spec/08-kite-verified.md`.
- UI: verify in a browser tool (assertions/DOM first, then one screenshot ≤1280×800).
- Never attach or enable any tool that can place orders or move money, including broker MCP servers.
