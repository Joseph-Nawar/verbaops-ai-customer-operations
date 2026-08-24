UV ?= uv

.PHONY: sync lint format-check typecheck test check dev down migrate commerce-migrate commerce-seed commerce-acceptance commerce-client-contract llm-gateway-contract agent-acceptance postgres-contract postgres-concurrency postgres-critical-race commerce-contract-check commerce-contract-update web-check web-smoke

sync:
	$(UV) sync

lint:
	$(UV) run ruff check .

format-check:
	$(UV) run ruff format --check .

typecheck:
	$(UV) run mypy src tests scripts

test:
	$(UV) run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance"

check:
	$(MAKE) sync
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) typecheck
	$(MAKE) test
	$(UV) run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance" --cov=verbaops --cov=novacommerce --cov-report=term-missing
	$(UV) run pre-commit run --all-files
	git diff --check

dev:
	$(UV) run python scripts/bootstrap_dev_env.py
	docker compose up --build

down:
	docker compose down

migrate:
	$(UV) run python scripts/bootstrap_dev_env.py
	docker compose up -d --wait postgres redis
	docker compose run --rm migrate

commerce-migrate:
	$(UV) run python scripts/bootstrap_dev_env.py
	docker compose up -d --wait commerce-postgres
	docker compose run --rm commerce-migrate

commerce-seed:
	$(UV) run python scripts/bootstrap_dev_env.py
	docker compose --profile seed run --build --rm commerce-seed

commerce-acceptance:
	$(UV) run python -m scripts.run_commerce_acceptance

commerce-client-contract:
	$(UV) run python -m scripts.run_commerce_client_contract

llm-gateway-contract:
	$(UV) run python -m scripts.run_llm_gateway_contract

agent-acceptance:
	$(UV) run python -m scripts.run_agent_acceptance

postgres-contract:
	$(UV) run python scripts/require_test_database.py
	$(UV) run pytest -m "postgres and contract"

postgres-concurrency:
	$(UV) run python scripts/require_test_database.py
	$(UV) run pytest -m "postgres and concurrency"

postgres-critical-race:
	$(UV) run python scripts/require_test_database.py
	$(UV) run pytest -m "postgres and concurrency and critical_race"

commerce-contract-check:
	$(UV) run python scripts/normalize_openapi.py --check contracts/novacommerce-openapi.json

commerce-contract-update:
	$(UV) run python scripts/normalize_openapi.py --update contracts/novacommerce-openapi.json

web-check:
	corepack pnpm --dir apps/web install --frozen-lockfile
	corepack pnpm --dir apps/web lint
	corepack pnpm --dir apps/web typecheck
	corepack pnpm --dir apps/web test
	corepack pnpm --dir apps/web build

web-smoke:
	corepack pnpm --dir apps/web smoke
