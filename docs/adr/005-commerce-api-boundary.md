# ADR-005: Access NovaCommerce through authenticated business APIs

Status: Accepted
Date: 2026-08-19

## Context

Commerce records include orders, shipments, refunds, returns, delivery slots, and tickets. Direct Agent Runtime database access would couple probabilistic reasoning to business state and make authorization, idempotency, and audit control harder.

## Decision

NovaCommerce is accessed through a separate authenticated Commerce Sandbox/API. The Agent Runtime invokes typed tools, the Policy Engine authorizes them, and the API owns domain state transitions. The Agent Runtime must never directly update NovaCommerce tables.

## Consequences

Business contracts become explicit and testable. The API can enforce idempotency, state transitions, result verification, and audit hooks. Local development may share infrastructure later without changing conceptual ownership.

## Alternatives considered

- Direct SQL from the Agent Runtime: rejected because it bypasses business invariants and the trust boundary.
- Let the LLM write arbitrary API requests: rejected because typed schemas and deterministic policy are required.
