# ADR-008: Hide external AI providers behind a gateway and interfaces

Status: Accepted
Date: 2026-08-19

## Context

RelayAI may use external model, speech, retrieval, and related providers. Provider outages, response differences, cost changes, and future substitutions must not leak into business-policy code.

## Decision

Expose external AI capabilities through an LLM Gateway/model abstraction and corresponding provider interfaces. Provider adapters return validated, observable results to the runtime; they do not receive authority to authenticate users, authorize business actions, or write commerce state.

## Consequences

Provider failure can be handled consistently with timeouts, fallback, abstention, retry, or escalation. Evaluation and cost attribution can compare providers and models. Interface design and adapters must preserve traceability, language slices, and schema validation.

## Alternatives considered

- Call one provider directly from business workflows: rejected because it couples policy to provider behavior and makes outages or substitution unsafe.
- Let providers own tool execution: rejected because external model output cannot be the authorization boundary.
