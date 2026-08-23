# M2F Stage 2 Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a permanent, HTTP-only, disposable-Docker NovaCommerce acceptance gate without changing production behavior or the M2E contracts.

**Architecture:** A Python orchestrator owns one ephemeral Compose project, credentials, canonical seed verification, fixture overlay, API readiness, black-box pytest execution, and unconditional teardown. Acceptance tests import only standard library, pytest, and httpx; setup-only fixture code may use NovaCommerce persistence in a one-off container. OpenAPI normalization is shared between snapshot generation and live acceptance.

**Tech Stack:** Python 3.12, pytest, httpx, FastAPI runtime image, Docker Compose, PostgreSQL 16.6, SQLAlchemy setup-only fixtures, existing uv/Makefile/GitHub Actions tooling.

**Spec:** `docs/superpowers/specs/2026-08-23-verbaops-m2f-stage2-acceptance-design.md`

## Global Constraints

- Base is exactly `c63e881770cbd61d163eef0b0b43542cef605f0f`.
- No changes under `src/verbaops/**`, `src/novacommerce/**`, migrations, canonical seed implementation/data, or `contracts/novacommerce-openapi.json`.
- Acceptance HTTP tests may not import `novacommerce`, `verbaops`, `sqlalchemy`, `asyncpg`, or `alembic`.
- The canonical seed remains seed `20260821`, as-of `2026-08-21`, fingerprint `f9c5a32603d7087eb820deffcbf8fdd27324e0fbd677d3f9c4774b335aadacdb`.
- The M2E OpenAPI snapshot remains SHA-256 `4EC1D8CDB34C797F45015EE0074DF1BF7D376DC866E7E3FF43EE7D43902A9F9E`.
- Existing CI job names and branch protection are unchanged; M2F adds only the `commerce-acceptance` job.
- Every task follows RED, expected failure, minimal GREEN, and regression verification before its commit.

---

### Task 1: Commit the approved design documents

**Files:**
- Create: `docs/superpowers/specs/2026-08-23-verbaops-m2f-stage2-acceptance-design.md`
- Create: `docs/superpowers/plans/2026-08-23-verbaops-m2f-stage2-acceptance.md`

- [ ] **Step 1: Validate the documents**

Run `git diff --check` and inspect that the spec records the HTTP-only boundary,
ephemeral stack, canonical seed, overlay, OpenAPI parity, teardown, CI, and
non-goals.

- [ ] **Step 2: Commit**

Run:
`git add docs/superpowers/specs/2026-08-23-verbaops-m2f-stage2-acceptance-design.md docs/superpowers/plans/2026-08-23-verbaops-m2f-stage2-acceptance.md`
and commit `docs: specify M2F stage2 acceptance`.

### Task 2: Extract pure OpenAPI contract functions

**Files:**
- Create: `scripts/openapi_contract.py`
- Modify: `scripts/normalize_openapi.py`
- Test: `tests/test_openapi_contract.py`

**Interfaces:** `normalize_openapi_document(document: dict) -> dict`, the
existing normalization helpers, and the existing CLI must remain available.

- [ ] **Step 1: Add a regression test**

Add a test that imports the pure functions from `scripts.openapi_contract`,
normalizes the generated application document, and asserts the snapshot bytes
and SHA are unchanged.

- [ ] **Step 2: Run RED**

Run `pytest tests/test_openapi_contract.py -q`; expect import failure because
the new module does not yet exist.

- [ ] **Step 3: Move only pure functions**

Move the normalization implementation to `scripts/openapi_contract.py` and
make `scripts/normalize_openapi.py` import/re-export those functions while
retaining its existing command-line behavior.

- [ ] **Step 4: Run GREEN**

Run `pytest tests/test_openapi_contract.py -q`, then run the update/check commands
and verify the committed snapshot hash and bytes do not change.

- [ ] **Step 5: Commit**

Commit `test: preserve OpenAPI normalization contract`.

### Task 3: Define the external scenario manifest

**Files:**
- Create: `tests/acceptance/fixtures/novacommerce-scenarios.json`
- Create: `tests/acceptance/commerce/__init__.py`
- Create: `tests/acceptance/fixtures/__init__.py`
- Test: `tests/test_m2f_acceptance_manifest.py`

**Interfaces:** `load_scenario_manifest(path) -> dict` and
`validate_scenario_manifest(manifest, seed_output) -> None` live in a setup-side
module, not the HTTP test package. The JSON contains all customer, product,
order, and slot scenario IDs required by the twelve route tests plus stable IDs
for overlay-owned rows.

- [ ] **Step 1: Add RED tests**

Test missing required scenario names, mismatched UUIDs, and a valid manifest;
the loader/validator imports must initially fail.

- [ ] **Step 2: Implement the setup-side loader**

Parse JSON, require UUID-shaped strings for IDs, require the locked canonical
scenario names, and compare every canonical ID against seed CLI `scenario_ids`.

- [ ] **Step 3: Run GREEN and commit**

Run the focused manifest tests and commit `test: establish acceptance scenario manifest`.

### Task 4: Add time-relative fixture overlay

**Files:**
- Create: `scripts/commerce_acceptance_fixtures.py`
- Test: `tests/test_m2f_acceptance_fixtures.py`

**Interfaces:** `AcceptanceFixtureConfig`,
`build_fixture_rows(as_of, manifest)`, and
`insert_fixture_rows(database_url, as_of, manifest)`.

- [ ] **Step 1: Add RED tests**

Test that fixture rows use one UTC as-of, have manifest-owned IDs, create a
recent delivered order and future slots, and reject any attempt to update or
delete canonical IDs.

- [ ] **Step 2: Implement minimal fixture rows**

Use the setup-only persistence imports to insert new customer-owned rows with
stable manifest IDs, a delivered timestamp inside the return window, a
reschedulable label-created shipment, and future slots. Validate foreign keys,
unique windows, and idempotent fresh-DB behavior.

- [ ] **Step 3: Run GREEN and commit**

Run focused fixture tests and commit `test: add time-relative acceptance fixtures`.

### Task 5: Add isolated Compose acceptance stack

**Files:**
- Create: `docker-compose.acceptance.yml`
- Test: `tests/test_m2f_compose_contract.py`

- [ ] **Step 1: Add RED contract tests**

Assert exactly the five acceptance services, pinned PostgreSQL `16.6-alpine`,
no `.env`/`.secrets`/VerbaOps/Redis/8010 references, health/completion
dependencies, and API port interpolation bound by the orchestrator.

- [ ] **Step 2: Implement Compose**

Define fresh named volumes and health checks. Use the runtime image for
migration/API/fixtures, the seed image for canonical seeding, and a one-off
fixture command. Keep the normal `docker-compose.yml` untouched.

- [ ] **Step 3: Run GREEN and commit**

Run the Compose contract tests and `docker compose -f docker-compose.acceptance.yml config`
with a temporary non-secret env file; commit `test: add isolated acceptance compose stack`.

### Task 6: Build the lifecycle orchestrator

**Files:**
- Create: `scripts/run_commerce_acceptance.py`
- Test: `tests/test_m2f_acceptance_runner.py`

**Interfaces:** `parse_api_port`, `run_compose`, `write_ephemeral_env`,
`teardown_compose`, and `main`.

- [ ] **Step 1: Add RED tests**

Test port bounds, unique project naming, restrictive temporary files, command
argument construction, credential non-printing, success cleanup, pytest failure
cleanup, and teardown failure exit behavior using a controlled subprocess seam.

- [ ] **Step 2: Implement the runner**

Capture one UTC `ACCEPTANCE_AS_OF`, create a temporary directory, generate
`secrets.token_urlsafe` password/token values, run each Compose phase, parse seed
JSON without logging it, verify fingerprint and manifest, wait for `/ready`, run
the marked suite with only required client env values, and always run
`down --volumes --remove-orphans`. Never add a keep-stack option.

- [ ] **Step 3: Run GREEN and commit**

Run focused runner tests and commit `test: add black-box commerce acceptance harness`.

### Task 7: Add black-box HTTP acceptance tests

**Files:**
- Create: `tests/acceptance/commerce/conftest.py`
- Create: `tests/acceptance/commerce/test_health_and_contract.py`
- Create: `tests/acceptance/commerce/test_reads.py`
- Create: `tests/acceptance/commerce/test_security.py`
- Create: `tests/acceptance/commerce/test_writes.py`
- Create: `tests/acceptance/commerce/test_idempotency.py`

**Interfaces:** Fixtures expose only an `httpx.AsyncClient`, parsed manifest,
service token, customer IDs, and overlay IDs. No application or database object
is exposed.

- [ ] **Step 1: Add RED tests**

Write HTTP tests for health/ready/OpenAPI parity, six GET routes, auth/context
contracts, six POST routes, replay/conflict, and deterministic rejection replay.
Use manifest IDs and disjoint mutation resources; do not assert mutable values
outside the test’s own resource.

- [ ] **Step 2: Run RED**

Run the marker explicitly without the acceptance environment and expect a hard
configuration failure, never a skip.

- [ ] **Step 3: Implement only test client fixtures**

Use `httpx` requests over the configured base URL. Make each file use the
`commerce_acceptance` marker and ensure the ordinary test selection excludes it.

- [ ] **Step 4: Run GREEN**

Run `make commerce-acceptance` against the disposable stack and verify all
acceptance assertions, including live OpenAPI parity and twelve route counts.

- [ ] **Step 5: Commit**

Commit `test: add black-box commerce acceptance tests`.

### Task 8: Enforce import isolation and integrate markers/tooling

**Files:**
- Create: `tests/architecture/test_acceptance_isolation.py`
- Modify: `pyproject.toml`, `Makefile`, `tests/test_postgres_classification.py`
- Test: relevant marker/CI contract tests

- [ ] **Step 1: Add RED static isolation test**

AST-scan `tests/acceptance/commerce/**/*.py` and fail on forbidden import roots.

- [ ] **Step 2: Implement marker and Make target**

Register the marker, exclude it from normal tests and coverage, add the phony
`commerce-acceptance` target invoking the orchestrator, and leave the M2E
PostgreSQL marker taxonomy unchanged.

- [ ] **Step 3: Run GREEN and commit**

Run the isolation and marker tests plus the normal suite; commit
`test: enforce black-box acceptance isolation`.

### Task 9: Add the permanent CI gate and README documentation

**Files:**
- Modify: `.github/workflows/ci.yml`, `README.md`
- Test: `tests/test_ci_contract.py`, `tests/test_readme_acceptance.py`

- [ ] **Step 1: Add RED tests**

Assert the fifth job is named `commerce-acceptance`, runs on pull requests and
pushes to main, uses pinned uv/Python/Ubuntu, has a bounded timeout, and invokes
`make commerce-acceptance` without changing existing job names.

- [ ] **Step 2: Implement CI/docs**

Update quality selectors to exclude `commerce_acceptance`, add the independent
job, and document the disposable HTTP-only acceptance command and five CI gate
names without claiming Stage 3 exists.

- [ ] **Step 3: Run GREEN and commit**

Run CI/README contract tests and commit `ci: add permanent commerce acceptance gate`.

### Task 10: Full acceptance verification and draft PR

**Files:** No new implementation files; verify all prior files.

- [ ] **Step 1: Run local gates**

Run `uv lock --check`, `uv sync --locked`, Ruff, format, mypy, the normal
`not postgres and not commerce_acceptance` suite with coverage, pre-commit,
`git diff --check`, and `make commerce-contract-check`.

- [ ] **Step 2: Run real PostgreSQL gates**

Run contract, concurrency, and both critical-race repetitions using the
established disposable PostgreSQL 16 procedure.

- [ ] **Step 3: Run the acceptance command**

Run `make commerce-acceptance`, then a deliberate failing runner invocation or
runner test, and prove both paths leave no Compose project resources.

- [ ] **Step 4: Verify scope and artifacts**

Check migration head, seed fingerprint, OpenAPI hash/live parity, six GET/six
POST methods, forbidden imports, and the no-production-change diff against
`c63e881770cbd61d163eef0b0b43542cef605f0f`.

- [ ] **Step 5: Review, push, and open draft PR**

Run the whole-branch review, push `stage2/m2f-stage2-acceptance`, open a draft
PR titled `Stage 2 M2F: add permanent Commerce acceptance gate`, wait for all
five CI jobs, and report exact evidence. Do not mark ready, merge, change branch
protection, or begin Stage 3.
