# NovaCommerce Domain & Persistence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the isolated NovaCommerce M2A package, PostgreSQL schema, operational FastAPI service, and local runtime without changing VerbaOps business behavior.

**Architecture:** NovaCommerce owns a separate package, settings model, SQLAlchemy metadata tree, Alembic environment, engine/session resources, and FastAPI lifespan. The root distribution contains both packages, while import tests and two Compose databases enforce the boundary. M2A exposes only operational endpoints and persistence definitions.

**Tech Stack:** Python 3.12, Pydantic Settings 2, SQLAlchemy 2 async ORM, Alembic async migrations, FastAPI, asyncpg, Docker Compose, uv, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-21-verbaops-stage2-commerce-sandbox-design.md` plus the M2A milestone brief supplied with this task.

## Global Constraints

- Keep `src/verbaops/` unchanged except project-wide packaging/test configuration required to include both packages.
- `novacommerce.__version__` must derive from distribution metadata `verbaops-ai`.
- NovaCommerce settings use `NOVACOMMERCE_`, are frozen, reject extras, and require a non-blank database URL only in staging/production.
- Use a separate DeclarativeBase, deterministic Alembic naming conventions, typed SQLAlchemy 2 ORM, UUID keys, timezone-aware timestamps, `NUMERIC(12,2)` money, and string-backed constrained enums.
- Do not add `/v1`, authentication, business logic, seeds, Faker, Redis, queues, AI, or direct VerbaOps/Commerce database access.
- Normal unit tests remain Docker-independent; database acceptance uses real PostgreSQL 16 only.
- Maintain branch-aware coverage at or above 80% for `verbaops` and `novacommerce`.

---

### Task 1: Lock the package boundary and configuration contract

**Files:**
- Create: `src/novacommerce/__init__.py`, `src/novacommerce/config/settings.py`
- Modify: `pyproject.toml`, `.env.example`, `.gitignore`, `.dockerignore`
- Test: `tests/novacommerce/test_package.py`, `tests/novacommerce/test_settings.py`, `tests/architecture/test_import_isolation.py`

**Interfaces:**
- Produce `novacommerce.__version__`, `Environment`, `LogLevel`, `DatabaseSettings`, `ObservabilitySettings`, and immutable `Settings`.
- Produce an architecture test that scans/imports both source trees and fails if either package imports the other.

- [ ] Write tests for distribution-derived version, all supported environments, nested `NOVACOMMERCE_` loading, blank deployed URLs, extra rejection, immutability, and import isolation.
- [ ] Run the focused tests and confirm they fail because the package/settings do not exist.
- [ ] Implement the package and settings with `SettingsConfigDict(env_prefix="NOVACOMMERCE_", env_nested_delimiter="__", extra="forbid", frozen=True)` and no VerbaOps imports.
- [ ] Run focused tests, Ruff, and mypy for the new files.

### Task 2: Build the independent ORM model tree

**Files:**
- Create: `src/novacommerce/db/base.py`, `src/novacommerce/db/models/{__init__,common,customer,product,order,shipment,delivery_slot,refund,return_,support_ticket,idempotency,commerce_event}.py`
- Test: `tests/novacommerce/test_models.py`

**Interfaces:**
- Produce `Base.metadata` containing exactly the 12 application tables and reusable `TimestampMixin`/`UUIDPrimaryKeyMixin` types.
- Produce enum classes for order, shipment, refund, return, support-ticket, and idempotency status values.

- [ ] Write metadata tests for table names, typed columns, foreign keys, relationships, all enum values, Decimal money columns, and required CheckConstraint/UniqueConstraint objects.
- [ ] Run the focused test and confirm it fails before model implementation.
- [ ] Implement one focused module per aggregate, constrained `String` enums, UUID primary keys, UTC-aware timestamps, JSONB payloads, and explicit indexes/constraints.
- [ ] Run model tests and inspect generated metadata before moving to migrations.

### Task 3: Add NovaCommerce database resources and operational service

**Files:**
- Create: `src/novacommerce/db/resources.py`, `src/novacommerce/api/{__init__,app,lifespan,runtime,routes}.py`
- Test: `tests/novacommerce/test_resources.py`, `tests/novacommerce/test_api.py`

**Interfaces:**
- Produce `DatabaseResources`, `create_database_resources(settings)`, `get_database_session(request)`, `ping_database(resources)`, and `dispose_database_resources(resources)`.
- Produce `create_app(settings)`, `create_runtime_app()`, and GET `/health`, `/ready`, `/version` routes with OpenAPI title `NovaCommerce Commerce Sandbox`.

- [ ] Write tests for engine options, request-scoped sessions, health/version/OpenAPI, ready 200, and safe ready 503 for missing or failed PostgreSQL.
- [ ] Run the focused tests and confirm the expected missing-module failure.
- [ ] Implement lifespan-owned resources with no module-level engine/session factory and no VerbaOps imports.
- [ ] Run focused tests and verify no `/v1` route is present.

### Task 4: Create the isolated Alembic migration

**Files:**
- Create: `alembic-commerce.ini`, `commerce_migrations/{env.py,script.py.mako,versions/0001_create_commerce_schema.py}`
- Test: `tests/migrations/test_commerce_migration.py`

**Interfaces:**
- Produce an async migration environment loading the database URL from NovaCommerce Settings with `target_metadata = Base.metadata`.
- Produce revision `0001_create_commerce_schema` whose downgrade removes only NovaCommerce schema objects.

- [ ] Write static migration tests for revision/dependency, target metadata, no credentials in ini, exact table list, and no changes under `migrations/`.
- [ ] Run the static test and observe failure before files exist.
- [ ] Implement the async env, deterministic naming, and one schema migration with clean downgrade.
- [ ] Run the migration unit tests; then run upgrade, second upgrade, downgrade, and re-upgrade against disposable PostgreSQL 16.

### Task 5: Extend bootstrap, Compose, Docker, Make, and CI contracts

**Files:**
- Modify: `scripts/bootstrap_dev_env.py`, `docker-compose.yml`, `Dockerfile`, `Makefile`, `.env.example`, `.gitignore`, `.dockerignore`, `.github/workflows/ci.yml`, `pyproject.toml`
- Test: `tests/bootstrap/test_bootstrap.py`, `tests/test_ci_contract.py`, `tests/novacommerce/test_compose_contract.py`

**Interfaces:**
- Add only `commerce-postgres`, `commerce-migrate`, and `commerce-api`; preserve Stage 1 services and credentials.
- Add `make commerce-migrate`, make `make dev` start the complete stack, and include both packages in build/type/coverage configuration.

- [ ] Write tests for fresh bootstrap, Stage 1 upgrade preserving existing values, partial NovaCommerce failure, Compose service/secret/healthcheck contracts, and coverage commands.
- [ ] Run focused tests and observe failures for the new contract.
- [ ] Implement additive bootstrap logic, pinned PostgreSQL 16 commerce service, migration dependency, runtime image inputs, port 8010, and project-wide quality commands.
- [ ] Run contract tests plus `docker compose config --quiet`.

### Task 6: Add real PostgreSQL acceptance coverage and documentation evidence

**Files:**
- Create: `tests/integration/test_commerce_postgres.py`, `docs/superpowers/evidence/2026-08-21-verbaops-stage2-m2a.md`
- Modify: `README.md`

**Interfaces:**
- Produce disposable-stack verification for migration idempotence, clean downgrade/re-upgrade, exact table isolation, FK enforcement, uniqueness/check constraints, and Decimal round-tripping.

- [ ] Add integration tests gated by an explicit `NOVACOMMERCE_TEST_DATABASE_URL`; skip only when the real PostgreSQL service is unavailable and report the skip.
- [ ] Run them against PostgreSQL 16, recording actual tables and constraint failures without SQLite.
- [ ] Verify the combined Compose stack, dependency failure/recovery, package import isolation, quality gates, image build, and `git diff --check`.
- [ ] Fill the technical-lead evidence packet with actual command output, status, and genuine open issues; do not mark M2A complete before all required checks pass.

### Task 7: Commit, publish, and hand off

**Files:**
- Git branch: `stage2/m2a-domain-persistence`

- [ ] Re-run all required fresh checks: `uv lock --check`, `uv sync --locked`, Ruff, format, mypy, coverage, pre-commit, `make check`, Compose config, runtime image build, and `git diff --check`.
- [ ] Review `git status --short`, `git log -5 --oneline`, and `git diff main...HEAD --stat`; stage only confirmed files.
- [ ] Commit as `feat: establish NovaCommerce domain persistence`.
- [ ] Push the branch and open a draft PR into `main` titled `Stage 2 M2A: establish NovaCommerce domain persistence`; do not merge.
- [ ] Wait for hosted CI, record its result/URL, and finish the handoff with exactly `M2A CANDIDATE — READY FOR TECHNICAL-LEAD REVIEW` only if every acceptance gate has fresh evidence; otherwise use `M2A NOT READY`.
