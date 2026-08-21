# ADR-004: Use modular service boundaries before microservices

Status: Accepted
Date: 2026-08-19

## Context

VerbaOps AI has distinct concerns—sessions, voice, runtime, retrieval, tools, policy, commerce, persistence, background work, and evaluation—but Phase 0 has no evidence for independent deployment or scaling boundaries.

## Decision

Define explicit logical modules and contracts while using a modular service architecture. Do not make Kubernetes-first deployment, Kafka, or premature microservices part of V1.

## Consequences

The system can evolve toward independent services where measured load, ownership, or reliability justifies it. Early implementation remains simpler and preserves clear trust boundaries. Redis, background work, object storage, and observability are documented as later capabilities rather than immediate infrastructure commitments.

## Alternatives considered

- Start with microservices and Kafka: rejected because operational complexity would precede measured need.
- Build a single undifferentiated application: rejected because it obscures the trust and ownership boundaries needed for safe AI operations.
