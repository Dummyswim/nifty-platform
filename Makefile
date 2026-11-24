-include Makefile.local
SHELL := /bin/bash
SYM ?= NIFTY 50
TF ?= 5m
N ?= 5
PY ?= python3
PIP ?= pip3
COMPOSE = docker compose --env-file .env -f deploy/docker-compose.yml

# step <name>,<command>: silent on success; first 15 lines on failure
define step
@out=$$($(2) 2>&1); rc=$$?; if [ $$rc -ne 0 ]; then echo "FAIL: $(1)"; echo "$$out" | head -n 15; exit $$rc; else echo "ok: $(1)"; fi
endef

.PHONY: up down ps logs check test migrate db-q init-env hash-password api-types parity bench e2e bars kite-smoke live demo start lock backup

up:
	@$(COMPOSE) up -d --build
down:
	@$(COMPOSE) down
ps:
	@$(COMPOSE) ps
logs:
	@$(COMPOSE) logs --tail 50 $(S)

check:
	$(call step,ruff check,cd backend && $(PY) -m ruff check .)
	$(call step,ruff format,cd backend && $(PY) -m ruff format --check .)
	$(call step,mypy,cd backend && $(PY) -m mypy src tests)
	$(call step,pytest,cd backend && $(PY) -m pytest -q -x)
	$(call step,tsc,cd web && npx tsc --noEmit -p tsconfig.json)
	$(call step,vitest,cd web && npx vitest run)

test:
	@cd backend && $(PY) -m pytest -q -x --tb=short $(patsubst backend/%,%,$(T))

migrate:
	@cd backend && $(PY) -m alembic upgrade head 2>&1 | tail -n 15

db-q:
	@test -n "$(Q)" || { echo 'usage: make db-q Q="select 1"'; exit 2; }
	@if command -v docker >/dev/null 2>&1 && $(COMPOSE) ps -q db 2>/dev/null | grep -q .; then \
	  Q="$(Q)" $(COMPOSE) exec -T -e Q -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=5000' db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "$$Q"' 2>&1 | head -n 50; \
	else \
	  set -a; . ./.env; set +a; \
	  PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=5000' psql "$${DATABASE_URL/+psycopg/}" -c "$(Q)" 2>&1 | head -n 50; \
	fi

bars:
	@cd backend && $(PY) -m nifty.cli bars --symbol "$(SYM)" --tf $(TF) --n $(N)

init-env:
	@$(PY) tools/init_env.py

hash-password:
	@$(PY) -m nifty.cli hash-password

api-types:
	@mkdir -p web/src/api
	@$(PY) -m nifty.cli openapi > web/src/api/openapi.json
	@cd web && npx openapi-typescript src/api/openapi.json -o src/api/types.ts 2>&1 | tail -n 5


parity:
	@test -n "$(E)" || { echo "usage: make parity E=<engine_id> [G=<golden dir>]"; exit 2; }
	@cd backend && $(PY) -m nifty.cli parity --engine $(E) $(if $(G),--golden $(abspath $(G)))

bench:
	@$(PY) tools/bench.py

e2e:
	@$(PY) tools/e2e_run.py

kite-smoke:
	@cd backend && $(PY) -m nifty.cli kite-smoke $(ARGS)

live:
	@cd backend && $(PY) -m nifty.collector

demo:
	@cd backend && $(PY) -m nifty.cli demo-replay --speed $(or $(SPEED),200)

start:
	@$(PY) tools/start.py $(ARGS)

# exact pins; dry-run resolve only, so the shared venv is not touched (D24)
lock:
	@cd /tmp && $(PY) -m pip install --dry-run --ignore-installed --quiet --report $(CURDIR)/.lock.json -e "$(CURDIR)/backend[dev]"
	@$(PY) tools/mklock.py .lock.json backend/requirements.lock

# database dump into the gitignored backups/ (restore steps: docs/HANDOFF.md)
backup:
	@mkdir -p backups
	@f=backups/nifty-$$(date +%Y%m%d-%H%M%S).sql.gz; $(COMPOSE) exec -T db sh -c 'pg_dump -U $$POSTGRES_USER $$POSTGRES_DB' | gzip > $$f && echo "wrote $$f"
