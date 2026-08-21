# VerbaOps AI M2D Transactional Commerce Writes Design

## Status

- M2A: complete
- M2B: complete
- M2C: complete
- M2D: active
- M2E–M2F: not started

## Goal

Add authenticated, customer-scoped transactional write commands to NovaCommerce while preserving the M2C read API, the external-style service boundary, and the existing `0001_create_commerce_schema` migration head.

## Locked architecture

Every POST follows service authentication, trusted customer context, request and idempotency-key validation, trusted-customer existence, a shared idempotent executor, a domain service, PostgreSQL row locks, a mutation, an optional `CommerceEvent`, a completed `IdempotencyRecord`, and one commit. The executor owns commit and rollback; domain services never call `commit()`.

The six M2C GET routes remain unchanged. M2D adds exactly six POST routes and no other API or infrastructure scope. There is no Redis idempotency, CQRS bus, broker, automatic transaction retry, payment movement, AI, or VerbaOps database coupling.

## Idempotency

`Idempotency-Key` is ASCII `[A-Za-z0-9._:-]`, length 8–255. Pre-execution failures create no record. A canonical SHA-256 JSON fingerprint includes operation, trusted customer UUID, target IDs, and validated body. A committed matching record replays its stored JSON with `X-Idempotent-Replay: true`; a mismatch returns `409/idempotency_key_reused`.

The executor inserts `in_progress`, runs the domain operation in the same `AsyncSession` transaction, stores the exact response body/status as JSON-safe data, creates at most one event, marks the record completed, and commits once. Deterministic business rejection is persisted and replayable. Commit uncertainty returns `503/write_outcome_unknown` without retrying the operation.

## Domain commands

- `POST /v1/orders`: lock products in UUID order, validate active stock, snapshot Decimal prices, decrement stock, create confirmed order/items/pending shipment, and emit `order.created`.
- `POST /v1/orders/{order_id}/cancel`: lock owned order, shipment, products, and slot; restore inventory and slot capacity exactly once; cancel order/shipment; emit `order.cancelled`.
- `POST /v1/orders/{order_id}/reschedule`: lock owned order, shipment, current and target slots in UUID order; move reservations or perform a same-slot no-op; emit `shipment.rescheduled` only for a state change.
- `POST /v1/returns`: lock delivered owned order/items, enforce the 30-day inclusive window and returnable quantities, create a requested return/items, and emit `return.requested`.
- `POST /v1/orders/{order_id}/refunds`: lock eligible owned order, enforce remaining refundable Decimal amount and the `$500.00` threshold, create refund, and emit `refund.requested`.
- `POST /v1/support-tickets`: create an open trusted-customer ticket with an optional owned order and emit `support_ticket.created`.

## Locking

Commands lock only required rows. Aggregate commands acquire order, shipment, order items, products sorted by UUID, and slots sorted by UUID. Create-order starts with products. State eligibility is evaluated again after locks. Concurrency tests use bounded timeouts and PostgreSQL 16.

## Failure safety

Controlled tests cover mutation-before-event, event-before-idempotency-completion, idempotency-before-commit, response loss after commit, and ambiguous commit acknowledgement. Every rollback case leaves business rows, events, and idempotency rows unchanged; response loss retries replay a committed record; ambiguous commit never internally reruns the command.

## Schema decision

The existing schema already supports all required M2D persistence. No migration or model schema change is permitted. The head remains `0001_create_commerce_schema`.
