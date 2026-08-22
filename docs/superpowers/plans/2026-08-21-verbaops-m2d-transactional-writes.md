# Transactional Commerce Writes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement M2D’s six authenticated, customer-scoped transactional POST commands with PostgreSQL idempotency, business rules, events, locking, and rollback safety.

**Architecture:** Thin FastAPI routes validate and delegate to domain services through one reusable write executor. The executor owns the session transaction and idempotency lifecycle; services lock and mutate SQLAlchemy models but never commit. Existing M2C schemas, auth, error envelope, database resources, and migration head remain in place.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async PostgreSQL, asyncpg, pytest/pytest-asyncio, disposable PostgreSQL 16 via Compose.

**Spec:** `docs/superpowers/specs/2026-08-21-verbaops-m2d-write-design.md`

## Global Constraints

- M2A, M2B, and M2C are complete; M2D is active; M2E–M2F are not started.
- No migration is allowed; commerce head remains `0001_create_commerce_schema`.
- All POST routes require service auth, trusted customer context, and `Idempotency-Key`.
- Domain services must not call `commit()`; the executor owns one commit/rollback boundary.
- No Redis idempotency, message broker, generic CQRS bus, automatic transaction retry, payment movement, AI, or VerbaOps database coupling.
- Money uses `Decimal`; response JSON uses exact decimal strings.

### Task 1: Idempotency foundation

**Files:** Create `src/novacommerce/idempotency.py`, `src/novacommerce/schemas/writes.py`, `tests/novacommerce/test_m2d_idempotency.py`; modify `src/novacommerce/api/errors.py` and `src/novacommerce/api/v1/dependencies.py`.

- [ ] Add tests for key syntax, canonical fingerprint stability, target/customer/operation differences, replay headers, and error codes.
- [ ] Run the focused tests and verify the missing modules/API fail for the expected reason.
- [ ] Implement `validate_idempotency_key`, `request_fingerprint`, `WriteOutcome`, and `execute_idempotent_write(session, *, key, operation, customer_id, fingerprint, operation_fn)`.
- [ ] Persist JSON-safe status/body, replay committed matches, reject mismatches, and map uncertain commit acknowledgement to `503/write_outcome_unknown` without retry.
- [ ] Run focused tests green and commit `feat: add transactional idempotency foundation`.

### Task 2: Order creation and cancellation

**Files:** Create `src/novacommerce/services/writes/orders.py`, `src/novacommerce/api/v1/write_orders.py`; modify `src/novacommerce/api/v1/router.py`, `src/novacommerce/schemas/orders.py`; create `tests/novacommerce/test_m2d_order_contract.py` and PostgreSQL order tests.

- [ ] Add failing schema/API tests for client-owned-field rejection, item bounds, create/cancel response shapes, status matrices, and idempotent replay.
- [ ] Implement Decimal order totals, deterministic product `FOR UPDATE` locking, stock decrement, pending shipment/tracking generation, and `order.created`.
- [ ] Implement customer-scoped locked cancellation, one-time inventory/slot restoration, cancelled timestamps/statuses, and `order.cancelled`.
- [ ] Add PostgreSQL success, rejection, replay, double-cancel, final-inventory-unit, and cancel-vs-reschedule tests with bounded concurrency.
- [ ] Run focused tests green and commit `feat: add transactional order writes`.

### Task 3: Shipment rescheduling

**Files:** Create `src/novacommerce/services/writes/reschedule.py`, `src/novacommerce/api/v1/write_reschedule.py`; create pure and PostgreSQL reschedule tests.

- [ ] Add failing tests for same-slot no-op, past/full/missing slots, status eligibility, and exact estimated-delivery derivation.
- [ ] Implement deterministic two-slot locking, reservation transfer, same-slot no-op, and `shipment.rescheduled` only on state change.
- [ ] Add final-capacity, opposite-direction, and cancel-vs-reschedule concurrency tests with timeouts.
- [ ] Run focused tests green and commit `feat: add transactional shipment rescheduling`.

### Task 4: Returns, refunds, and tickets

**Files:** Create `src/novacommerce/services/writes/returns.py`, `refunds.py`, `tickets.py`, `src/novacommerce/api/v1/write_returns.py`, `write_refunds.py`, `write_tickets.py`; extend `src/novacommerce/schemas/` and router; add pure/API/PostgreSQL tests.

- [ ] Add failing tests for return-window boundaries, returnable quantity, refund threshold/remaining amount, ticket ownership, validation, response schemas, and exact event types.
- [ ] Implement locked return item accounting with rejected returns excluded, inclusive 30-day eligibility, Decimal refund accounting with rejected refunds excluded, and trusted ticket creation.
- [ ] Add refund race, returnable-quantity race, ticket duplicate, cross-customer, deterministic-rejection, and replay tests.
- [ ] Run focused tests green and commit `feat: add return refund and ticket writes`.

### Task 5: Failure injection and invariant contracts

**Files:** Modify `src/novacommerce/idempotency.py`; create `tests/integration/test_m2d_transaction_failures.py`, `test_m2d_idempotency_invariants.py`.

- [ ] Add failing controlled tests for each rollback point, response loss, and ambiguous commit acknowledgement.
- [ ] Implement narrow executor hooks supplied through explicit test-callable collaborators, without production retries or hidden testing branches.
- [ ] Verify business/event/idempotency atomicity and same-key replay after response loss.
- [ ] Run all accumulated real PostgreSQL M2A–M2D suites and commit `test: cover transactional failure and idempotency invariants`.

### Task 6: Live acceptance and final verification

**Files:** Create/update focused integration acceptance tests and M2D evidence notes only; do not modify migrations.

- [ ] Run fresh `make dev`, `make commerce-seed`, and the HTTP create→read→reschedule→cancel flow with replay checks.
- [ ] Exercise returns, refund thresholds, tickets, rejection cases, health, and no-schema-drift queries.
- [ ] Run all required lint/type/test/pre-commit/Compose/runtime/seed checks and confirm coverage is at least 80%.
- [ ] Verify clean git state, commit `feat: add transactional idempotent commerce writes`, push the branch, open the draft PR, and wait for hosted `quality` and `docker-build` success.
