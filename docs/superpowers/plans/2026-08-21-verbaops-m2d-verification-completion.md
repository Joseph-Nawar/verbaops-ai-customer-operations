# M2D Verification Coverage Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the missing M2D fingerprint, idempotency, transaction-atomicity, business-boundary, and PostgreSQL concurrency evidence without changing approved production behavior unless a new test exposes a real defect.

**Architecture:** Extend the existing pure M2D contract tests and PostgreSQL integration suite. Integration races will use independent `AsyncSession`/connection instances, real migrated PostgreSQL 16, deterministic seeded scenarios, and bounded `asyncio.wait_for` timeouts. The idempotency executor remains the sole transaction owner; domain services may only flush and append events.

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, HTTPX ASGI transport, SQLAlchemy async PostgreSQL, Alembic, Docker Compose, uv.

**Spec:** `docs/superpowers/specs/2026-08-21-verbaops-m2d-write-design.md`

## Global Constraints

- Do not merge PR #4 or begin M2E.
- Preserve branch `stage2/m2d-transactional-writes` and candidate `ef7d151e3106061af185211e500a7b326bb015a0` before changes.
- Do not modify production behavior merely to increase coverage.
- For every new behavior test, execute RED first; if it passes immediately, record that existing behavior was verified.
- Use real PostgreSQL 16 for persistence, idempotency, rollback, and concurrency tests; never SQLite.
- Keep migration head `0001_create_commerce_schema` and migration diff empty.
- Keep the runtime API read/write scope and package boundary unchanged.

---

### Task 1: Fingerprint and cancellation contract tests

**Files:**
- Modify: `tests/novacommerce/test_m2d_idempotency.py`
- Modify: `tests/novacommerce/test_m2d_rules.py`

- [x] Add explicit validated-body construction tests showing semantically equivalent JSON formatting and key ordering produce one fingerprint, while operation/customer/target/body changes produce different fingerprints.
- [x] Add assertions that correlation IDs and bearer tokens are absent from the fingerprint API and cannot affect its output.
- [x] Replace the representative cancellation assertions with a parameterized complete matrix covering every allowed and blocked order/shipment status pair.
- [x] Run the new tests before changing production code. The current implementation passed.

### Task 2: PostgreSQL same-key, rejection, and same-slot evidence

**Files:**
- Modify: `tests/integration/test_m2d_write_postgres.py`

- [x] Add a helper for isolated table deltas and exact per-key row/event counts.
- [x] Add real PostgreSQL tests for same key with different target, operation, and customer, asserting `409 idempotency_key_reused` and no cross-customer replay.
- [x] Strengthen concurrent identical-key create assertions to exactly one new order, one event, one completed idempotency row, and equivalent responses.
- [x] Add isolated pre-execution failure counts and deterministic shipped-cancellation rejection counts/replay assertions.
- [x] Add same-slot reschedule assertions for unchanged reservation and shipment assignment, zero event delta, one completed idempotency row, and replay.
- [x] Execute the focused tests against disposable PostgreSQL 16.

### Task 3: Real PostgreSQL concurrency matrix

**Files:**
- Modify: `tests/integration/test_m2d_write_postgres.py`
- Modify: `tests/integration/conftest.py` only if a shared bounded-session helper is required; do not add production fixtures.

- [x] Add independent-session races for final inventory, double cancellation, cancel versus reschedule, final slot capacity, opposite-direction reschedules, final returnable quantity, refund capacity, and duplicate ticket key.
- [x] Wrap each race in bounded `asyncio.wait_for`/`asyncio.timeout` and report HTTP outcomes without leaking raw database exceptions.
- [x] Assert exact final database invariants, event deltas, and idempotency deltas required by the M2D contract.
- [x] Run each new test individually first, then run the complete M2D PostgreSQL file.

### Task 4: Failure-injection and post-commit evidence

**Files:**
- Modify: `tests/integration/test_m2d_write_postgres.py`

- [x] Add real state-changing operation callbacks/hooks for failure after domain mutation before event, after event before completion, and after completion before commit. Each asserts business rows, events, and idempotency records are absent after rollback.
- [x] Strengthen post-commit response-loss coverage with a real business mutation and exact mutation/event/idempotency counts before and after replay.
- [x] Strengthen ambiguous commit coverage with invocation count and both persisted-commit replay and non-persisted retry paths without redesign.
- [x] Run focused RED/GREEN tests and verify no production defect was exposed.

### Task 5: Live acceptance and regression gate

**Files:**
- Modify: relevant test documentation only if it records the newly completed evidence.

- [x] Run disposable Compose HTTP workflow and capture resource IDs, stock/slot deltas, event types, idempotency operation names, and replay invariants.
- [x] Run all PostgreSQL files separately and report per-file counts/durations plus aggregate totals.
- [x] Run the complete locked regression commands, migration-diff check, Docker builds, and architecture/import checks.
- [x] Confirm production source is unchanged; all tests passed.

### Task 6: Commit and hosted verification

**Files:**
- Commit only the focused tests and relevant test documentation, plus any minimal production fix proven necessary by RED/GREEN evidence.

- [ ] Review status and diff for unrelated changes.
- [ ] Commit as `test: complete M2D concurrency and atomicity coverage` when production code is unchanged.
- [ ] Push the same branch without merging PR #4.
- [ ] Wait for hosted CI on the exact new HEAD and require `quality=success` and `docker-build=success`.
