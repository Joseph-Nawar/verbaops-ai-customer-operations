UV ?= uv

.PHONY: sync lint format-check typecheck test check dev down migrate

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
	$(UV) run pytest --cov=relayai --cov-report=term-missing
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
