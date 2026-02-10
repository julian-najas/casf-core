.PHONY: help lint test opa-test up down smoke clean

COMPOSE := docker compose -f deploy/compose/docker-compose.yml
VERIFIER := services/verifier
VENV := $(VERIFIER)/.venv/Scripts/activate

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── Quality ──────────────────────────────────────────────

lint: ## Run ruff + mypy
	cd $(VERIFIER) && python -m ruff check src/ tests/
	cd $(VERIFIER) && python -m mypy src/verifier/

test: ## Run pytest (requires Postgres + Redis + OPA)
	cd $(VERIFIER) && python -m pytest tests/ -v

opa-test: ## Run OPA policy tests via Docker
	docker run --rm -v "$(CURDIR)/policies:/policies:ro" \
		openpolicyagent/opa:0.63.0 test /policies -v

opa-fmt: ## Check OPA policy formatting
	docker run --rm -v "$(CURDIR)/policies:/policies:ro" \
		openpolicyagent/opa:0.63.0 fmt --diff /policies

opa-check: ## Static analysis of OPA policies
	docker run --rm -v "$(CURDIR)/policies:/policies:ro" \
		openpolicyagent/opa:0.63.0 check /policies

# ── Stack ────────────────────────────────────────────────

up: ## Start full stack (build + detach)
	$(COMPOSE) up --build -d

down: ## Stop stack and remove volumes
	$(COMPOSE) down -v

ps: ## Show stack status
	$(COMPOSE) ps

logs: ## Tail stack logs
	$(COMPOSE) logs -f --tail=50

# ── Smoke ────────────────────────────────────────────────

smoke: up ## Run full smoke test (starts stack first)
	powershell -ExecutionPolicy Bypass -File deploy/compose/scripts/smoke_integration.ps1

# ── Housekeeping ─────────────────────────────────────────

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true

check: lint test opa-test ## Run all checks (lint + test + OPA)
