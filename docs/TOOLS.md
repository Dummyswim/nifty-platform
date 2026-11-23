# Tools policy (load when choosing tools, and in C00/C15)

## 1. Capability → tool (Copilot name / Claude Code name)
| Need | Use | Rules |
|---|---|---|
| Read | `view` (view_range) / Read(offset, limit) | ranges for files >200 lines; Pine only by cited range |
| Find files | `glob` / Glob | |
| Search text | `grep` / Grep | scope with a glob; `files_with_matches` first, then `content` with `head_limit` |
| New file | `create` / Write | |
| Change file | `edit` / Edit, MultiEdit | batch non-overlapping edits per file in one turn |
| Run program | `bash` / Bash | one purpose per call, chain with `&&`; sync ≤2 min, else async/background; servers detached; never write files via heredoc/`sed -i`/`tee` |
| Fetch docs | `web_fetch` / WebFetch | only URLs named in a chunk; distil into `docs/spec/08-kite-verified.md` |
| Ask user | `ask_user` / AskUserQuestion | one question, choices first, recommended first |
| Sub-agent | `task` (`task`/`explore`) / Task | noisy commands → `task`; multi-file read-only research → `explore`; never for one continuous trace |
| Checklist | session todo table / TodoWrite | only when a chunk has >5 steps |
| Browser | `browser` canvas / Playwright MCP | UI chunks only |

## 2. Project tools (sanctioned verification path)
Created in C00, extended later. Each prints ≤40 lines by default, accepts `V=1` for verbose, exit code is truth, and never prints env values.
- `make up | down | ps | logs S=<svc>` — Compose (127.0.0.1 binds only)
- `make check` — ruff + mypy + `pytest -q -x` (+ web `tsc`, `vitest`); failures show the first 15 lines of each failing step
- `make test T=<path | -k expr>` — `pytest -q -x --tb=short`
- `make parity E=<engine> [G=<golden dir or csv>]` — Tier A/B/C report (counts, first 5 diffs, max abs error)
- `make bench` — 100k-bar replay: wall time, peak RSS
- `make api-types` — OpenAPI → `web/src/api/types.ts`
- `make e2e` — Playwright smoke (from C05)
- `make db-q Q="select …"` — read-only transaction, `statement_timeout=5s`, ≤50 rows
- `make bars SYM=… TF=… N=…` — summary + last N bars
- `make migrate` — Alembic upgrade head
- `make init-env` — creates `.env` from `.env.example` with generated random `POSTGRES_PASSWORD` and `APP_SECRET_KEY` (no overwrite, prints nothing secret). `make hash-password` — user-run: prompts, prints the `APP_PASSWORD_HASH=…` line to paste into `.env`.
- Later chunks add: `make kite-smoke` (C07, user-run, needs credentials), `make demo` and `make live` (C08: CSV demo replay; `docker compose --profile live up -d collector`), `make lock` and `make backup` (C15). A target not yet implemented prints `not available until Cxx` and exits 2.
- Python entry point: `python -m nifty.cli <cmd>` (argparse, no extra deps); `Makefile.local` (gitignored) sets `PY=` to the local venv path.

## 3. Optional MCP / skills (install once, read-only)
- Browser automation: the Copilot app's built-in `browser` canvas, or Playwright MCP elsewhere. Order: DOM/text assertions → console errors → one screenshot.
- Library docs lookup (e.g. Context7) for lightweight-charts, FastAPI, SQLAlchemy, TimescaleDB. Prefer local typings first: `grep` in `web/node_modules/lightweight-charts/dist/typings.d.ts` and installed Python packages.
- Postgres MCP: not needed (`make db-q`). GitHub MCP/`gh`: only if the user pushes the repo. Computer-use/desktop automation: not needed.
- **Forbidden:** any MCP/tool that can place, modify or cancel orders or move funds. Broker MCP servers (e.g. Zerodha's Kite MCP) must not be attached to this project's agent if their tool list contains order tools.

## 4. Output budget
Test/lint/build output: summary only (`-q`, `--tail 50`). DB: `LIMIT`. Data: `head`, `wc -l`, `describe()`; never dump a CSV. Logs: `--tail 50`. Screenshots: ≤1280×800, only after assertions pass. Fetched docs: keep only the facts a spec needs.
