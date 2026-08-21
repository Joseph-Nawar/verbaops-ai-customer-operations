UV ?= uv

.PHONY: sync lint format-check typecheck test check dev down migrate commerce-migrate commerce-seed

sync:
	$(UV) sync

lint:
	$(UV) run ruff check .

format-check:
	$(UV) run ruff format --check .

typecheck:
	$(UV) run mypy src tests

test:
	$(UV) run pytest

check:
	$(MAKE) sync
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) typecheck
	$(MAKE) test
	$(UV) run pytest --cov=verbaops --cov=novacommerce --cov-report=term-missing
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
