# M2E Hosted PostgreSQL and API Contract Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add marker-enforced PostgreSQL contract/concurrency gates, deterministic OpenAPI contract tooling, local parity targets, and exact hosted CI/branch-protection governance without changing production source or schema.

**Architecture:** PostgreSQL integration tests remain under `tests/integration`; a collection-time plugin classifies that structural location and enforces marker invariants. A standalone script imports the real FastAPI app, normalizes only `/v1` operations and their referenced schemas, and powers explicit Make targets. GitHub Actions runs separate isolated PostgreSQL 16 contract and concurrency jobs, while `quality` and `docker-build` retain their exact names.

**Tech Stack:** Python 3.12, pytest markers/hooks, FastAPI OpenAPI generation, SQLAlchemy/Alembic, PostgreSQL 16 services, Make, GitHub Actions, `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-08-22-verbaops-m2e-ci-contract-design.md`

## Global Constraints

- `git diff main...HEAD -- src` must be empty.
- `git diff main...HEAD -- commerce_migrations migrations` must be empty.
- Migration head remains `0001_create_commerce_schema`.
- M2B identity remains seed `20260821`, `as_of` `2026-08-21`, fingerprint `f9c5a32603d7087eb820deffcbf8fdd27324e0fbd677d3f9c4774b335aadacdb`.
- Do not add business behavior, routes, schema changes, transaction changes, or M2F work.
- Real PostgreSQL tests use `postgres` plus exactly one of `contract` or `concurrency`.
- Critical races use `postgres`, `concurrency`, and `critical_race`.
- Hosted jobs run tests once except the explicitly required two critical-race repeat passes.

---

### Task 1: Establish marker taxonomy and collection enforcement

**Files:**
- Modify: `pyproject.toml` marker registration.
- Create: `tests/conftest.py` collection validator.
- Modify: `tests/integration/test_commerce_postgres.py` markers.
- Modify: `tests/integration/test_commerce_seed_postgres.py` markers.
- Modify: `tests/integration/test_m2c_read_api_postgres.py` markers.
- Modify: `tests/integration/test_m2d_write_postgres.py` markers.
- Create: `tests/test_postgres_classification.py` direct validator tests.

**Interfaces:**
- `pytest_collection_modifyitems(session, config, items)` validates structural PostgreSQL tests.
- Contract modules use `pytestmark = [pytest.mark.postgres, pytest.mark.contract]`.
- The M2D module uses `pytestmark = [pytest.mark.postgres, pytest.mark.concurrency]`.
- Six approved race functions receive `pytest.mark.critical_race`.

- [ ] **Step 1: Write failing marker tests**

Add direct tests for missing `postgres`, missing contract/concurrency classification, both classifications, invalid critical-race combinations, and valid combinations using minimal collected-item doubles.

- [ ] **Step 2: Run marker tests to verify RED**

Run `uv run pytest tests/test_postgres_classification.py -q`. The initial failure must identify the absent validator or taxonomy.

- [ ] **Step 3: Implement collection validation and classify existing modules**

Register all four markers in `pyproject.toml`. Treat tests collected from `tests/integration` whose module name ends in `_postgres.py` as real PostgreSQL tests. Require `postgres` and exactly one of `contract` or `concurrency`; require `postgres` and `concurrency` for `critical_race`; reject `critical_race` with `contract`.

- [ ] **Step 4: Run validator and collection checks GREEN**

Run `uv run pytest tests/test_postgres_classification.py -q`, then collect each authoritative marker expression and verify the selected counts.

- [ ] **Step 5: Commit taxonomy**

Run `git add pyproject.toml tests/conftest.py tests/test_postgres_classification.py tests/integration` and commit `test: classify PostgreSQL contract and concurrency suites`.

### Task 2: Add isolated PostgreSQL fixtures and local parity targets

**Files:**
- Create: `tests/integration/conftest.py` shared database reset helpers.
- Modify: integration modules to consume shared migration/reset fixtures without order dependence.
- Modify: `Makefile` with `postgres-contract`, `postgres-concurrency`, `postgres-critical-race`, `commerce-contract-check`, and `commerce-contract-update`.
- Modify: `tests/test_ci_contract.py` command/target contracts.

**Interfaces:**
- `database_url` reads only `NOVACOMMERCE_TEST_DATABASE_URL` and fails clearly when a PostgreSQL target is invoked without it.
- `reset_commerce_application_tables(engine)` deletes application rows in dependency-safe order and leaves `alembic_version` intact.
- PostgreSQL Make targets invoke `uv run pytest -m ...` with the externally supplied URL and no fallback URL.

- [ ] **Step 1: Add failing target and fixture contract tests**

Test missing-URL failure, `make check` database independence through `-m "not postgres"`, and reset preservation of `alembic_version`.

- [ ] **Step 2: Run targeted tests to verify RED**

Run `uv run pytest tests/test_ci_contract.py -q` and confirm the new target/fixture contract is not yet present.

- [ ] **Step 3: Implement shared fixture/reset behavior and Make targets**

Use one externally supplied URL per process/job. Apply migration setup through the existing Commerce Alembic command in CI, then reset only application tables between tests. Keep empty tests empty and call `seed_database` only in tests that require canonical data.

- [ ] **Step 4: Run local database-independent checks GREEN**

Run `uv run pytest -m "not postgres" --cov=verbaops --cov=novacommerce --cov-report=term-missing` and `make check`.

- [ ] **Step 5: Commit local parity**

Commit `test: add local PostgreSQL parity targets` with the Make, fixture, and test changes.

### Task 3: Build deterministic OpenAPI normalization tooling

**Files:**
- Create: `scripts/normalize_openapi.py`.
- Create: `contracts/novacommerce-openapi.json` using the update command.
- Create: `tests/test_openapi_contract.py`.
- Modify: `Makefile` contract targets.

**Interfaces:**
- `normalize_openapi(document: Mapping[str, Any]) -> dict[str, Any]` returns the normalized contract.
- `generate_normalized_openapi() -> bytes` builds the real app OpenAPI document and returns stable UTF-8 JSON bytes.
- `collect_references(document, root) -> dict[str, Any]` recursively closes `$ref` dependencies.
- `scripts/normalize_openapi.py --check PATH` compares generated bytes without writing.
- `scripts/normalize_openapi.py --update PATH` deliberately writes the artifact.

- [ ] **Step 1: Write failing normalizer tests**

Cover deterministic consecutive generation, cosmetic metadata removal, path/method drift, security drift, parameter requiredness, request-body schema, response status/schema, component field type/requiredness, stale snapshot detection, and recursive reference closure.

- [ ] **Step 2: Run tooling tests to verify RED**

Run `uv run pytest tests/test_openapi_contract.py -q` and confirm the missing normalizer fails for the expected reason.

- [ ] **Step 3: Implement conservative normalization**

Filter `paths` to `/v1`; retain methods, parameters, request bodies, responses, security, and referenced component closure; strip only documented cosmetic metadata; sort keys; emit four-space JSON with one final newline.

- [ ] **Step 4: Generate and verify the artifact**

Run `make commerce-contract-update`, inspect `git diff -- contracts/novacommerce-openapi.json`, run `make commerce-contract-check`, run update again, and prove `git diff --exit-code -- contracts/novacommerce-openapi.json`.

- [ ] **Step 5: Commit the contract gate**

Commit `test: add NovaCommerce OpenAPI contract gate` with the script, artifact, tests, and Make targets.

### Task 4: Add exact route and semantic contract assertions

**Files:**
- Create: `tests/novacommerce/test_m2e_contract.py`.
- Modify: existing M2C/M2D contract tests only when a shared test helper is required.

**Interfaces:**
- `business_route_set(app) -> set[tuple[str, str]]` returns only `/v1` operations.

- [ ] **Step 1: Write failing exact-route assertion**

Assert the twelve approved `(method, path)` pairs and reject any extra, missing, or wrong-method operation. Add focused assertions for authentication, trusted context, anti-enumeration, shared reads, write Idempotency-Key, replay, conflict, deterministic rejection replay, stable errors, and read-only GET state.

- [ ] **Step 2: Run the focused contract test to verify RED**

Run `uv run pytest tests/novacommerce/test_m2e_contract.py -q`.

- [ ] **Step 3: Implement only test/tooling helpers**

Reuse existing M2C/M2D behavior tests; do not change `src/` behavior or add routes.

- [ ] **Step 4: Run focused contract tests GREEN**

Run `uv run pytest tests/novacommerce/test_m2e_contract.py tests/test_openapi_contract.py -q`.

- [ ] **Step 5: Commit route/semantic coverage**

Commit `test: enforce NovaCommerce route contract`.

### Task 5: Add hosted PostgreSQL CI jobs and no-rerun safeguards

**Files:**
- Modify: `.github/workflows/ci.yml`.
- Modify: `tests/test_ci_contract.py` workflow assertions.

**Interfaces:**
- Jobs are exactly `postgres-contract` and `postgres-concurrency`.
- Contract runs `uv run pytest -m "postgres and contract"` once.
- Concurrency runs `uv run pytest -m "postgres and concurrency"` once, then the critical expression twice.
- Both jobs use independent PostgreSQL 16 services, health checks, migration setup, safe test credentials, and bounded timeouts.

- [ ] **Step 1: Write failing workflow contract tests**

Assert exact job names, PostgreSQL 16 services, health checks, migration setup, marker commands, three concurrency passes, no retry/suppression patterns, and preservation of `quality`/`docker-build` names.

- [ ] **Step 2: Run workflow tests to verify RED**

Run `uv run pytest tests/test_ci_contract.py -q`.

- [ ] **Step 3: Implement the two jobs**

Use existing pinned setup actions and `uv` conventions. Set `NOVACOMMERCE_TEST_DATABASE_URL` to a service-only PostgreSQL URL and provide a safe 32+ character test service token. Use `postgres:16` with health checks and run Commerce migrations once per job.

- [ ] **Step 4: Run workflow contract tests GREEN**

Run `uv run pytest tests/test_ci_contract.py -q`.

- [ ] **Step 5: Commit hosted CI**

Commit `ci: add hosted PostgreSQL safety gates`.

### Task 6: Run local PostgreSQL acceptance and full regression

**Files:**
- No production files may be modified.
- Modify: evidence documentation only when measured results need recording.

- [ ] **Step 1: Start one disposable PostgreSQL 16 service and apply migrations**

Use an isolated test-only database/user and export only `NOVACOMMERCE_TEST_DATABASE_URL`; never print credentials or full credential-bearing URLs.

- [ ] **Step 2: Run local marker commands exactly**

Run the contract marker once, full concurrency once, and the critical marker twice more. Record passed/failed/skipped counts and durations separately.

- [ ] **Step 3: Run full local regression**

Run the locked dependency, lint, format, type, normal deselected pytest with coverage, pre-commit, `make check`, contract check, Compose config, both Docker builds, and `git diff --check` commands from the M2E specification.

- [ ] **Step 4: Verify no schema/source drift**

Run `git diff main...HEAD -- src` and `git diff main...HEAD -- commerce_migrations migrations`; both must be empty.

### Task 7: Push draft PR, verify hosted checks, and configure protection

**Files:**
- Repository settings via authenticated `gh` API; no repository source file.

- [ ] **Step 1: Verify branch and commit state, then push**

Run `git status --short`, `git branch -vv`, `git log -10 --oneline`, and push `stage2/m2e-hosted-contract-gates`.

- [ ] **Step 2: Open the draft PR**

Create a draft PR into `main` titled `Stage 2 M2E: add hosted PostgreSQL and API contract gates`.

- [ ] **Step 3: Wait for exact-head CI**

Verify rendered checks are exactly `quality`, `postgres-contract`, `postgres-concurrency`, and `docker-build`, all successful on the exact PR head.

- [ ] **Step 4: Inspect existing main protection before update**

Use authenticated GitHub API calls for `main` protection/rules and stop if the account cannot express the required policy.

- [ ] **Step 5: Configure exact protection after checks are green**

Require pull requests, strict/up-to-date branches, and the four exact contexts. Add no review, CODEOWNERS, signed-commit, deployment-approval, or administrator-lockout requirement.

- [ ] **Step 6: Re-fetch and verify protection**

Prove `main` is protected, PR path is required, strict is true, exact contexts are present, and no unintended governance requirements were added.

- [ ] **Step 7: Final handoff**

Report branch/SHA/PR, marker counts, local and hosted durations, artifact SHA-256, route set, protection state, full regression, Git evidence, and open issues. Do not merge and do not begin M2F.
