# C15 · Hardening, lockfiles, handoff
effort: low · deps: all earlier chunks · reads: `docs/TOOLS.md` · `docs/spec/05-backend.md` (Compose) · `docs/STATE.md` · webapp prompt L290–314 (Deliverables, Success criteria; view_range)
pine: — · tools: bash (`make check`, `make bench`, `docker compose config`, `git grep`) · create/edit · `task` for builds
**If short:** 1 security checks + lockfiles · 2 evidence table · 3 HANDOFF · 4 README/PORTING.

**Goal.** Reproducible builds, verified safety, honest evidence for every success criterion, and a handoff someone else can follow.

**Do**
1. `make lock` (D24) without touching the shared venv: `pip install --dry-run --ignore-installed --report .lock.json -e "backend[dev]"` with the local venv's pip, then `tools/mklock.py` → `backend/requirements.lock` (exact pins). Dockerfiles switch to `-c backend/requirements.lock`; web uses `npm ci`.
2. Security checks (each as a test or a command whose result you record):
   - the D19 order-endpoint guard passes;
   - `git grep -nEi "(api_secret|access_token|request_token|password)\s*[:=]\s*['\"][^'\"]+"` shows no real secrets; `.env` is untracked;
   - every published port is bound to 127.0.0.1;
   - a test enumerates the OpenAPI routes: all except `healthz` need the cookie; the WS closes without it;
   - no wildcard CORS; cookie flags; log redaction tests pass.
3. `make backup` (`pg_dump` to gitignored `backups/`) and restore steps in HANDOFF.
4. `docker compose --env-file .env.example -f deploy/docker-compose.yml config -q`; if docker=yes also `docker compose build` and a `make up` smoke (healthz, readyz, one engine run), then `make down`.
5. `README.md` (≤60 lines): what it is, quickstart, the daily Kite login, make targets, the safety stance (read-only, never orders).
6. `docs/HANDOFF.md` (≤120 lines) covering webapp Deliverables 1–11: architecture (ASCII diagram), DB schema summary, API design, ASCII wireframes (Chart, Options, Backtests + audit, Analytics, Research, Settings), Docker Compose, Zerodha/Kite integration, Pine conversion design, backtesting engine, audit dashboard, MVP roadmap (done vs not), production roadmap.
7. `docs/engines/PORTING.md` (≤30 lines): checklist for porting another Pine script (map → ranges → params + `ui` split → bar order → debug plots → golden export → tier tests → D14 properties → `ready`).
8. Evidence table for the webapp Success criteria (L306–314), one row each: criterion → command, test or UI check → result, or `not verified: <reason>`. Include the final `make check` and `make bench` numbers and the parity status per engine (golden present or missing).
9. Prune STATE to ≤150 lines (collapse done-chunk notes), set `next_chunk: DONE`.

**Acceptance.** `make check` green; lockfile installs in a clean Docker build when docker=yes; HANDOFF covers all 11 deliverables; every success criterion has evidence or an explicit gap.
**Record in STATE:** final status, remaining gaps and risks (golden exports pending, Kite live unverified, calendar unverified).
