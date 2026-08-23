UV ?= uv

.PHONY: sync lint format-check typecheck test check dev down migrate commerce-migrate commerce-seed postgres-contract postgres-concurrency postgres-critical-race commerce-contract-check commerce-contract-update

sync:
	$(UV) sync

lint:
	$(UV) run ruff check .

format-check:
	$(UV) run ruff format --check .

typecheck:
	$(UV) run mypy src tests scripts

test:
	$(UV) run pytest -m "not postgres"

check:
	$(MAKE) sync
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) typecheck
	$(MAKE) test
	$(UV) run pytest -m "not postgres" --cov=verbaops --cov=novacommerce --cov-report=term-missing
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
