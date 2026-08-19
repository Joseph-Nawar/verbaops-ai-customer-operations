# ADR-006: Make English and Arabic first-class, with deepest Egyptian specialization

Status: Accepted
Date: 2026-08-19

## Context

NovaCommerce serves a MENA-oriented audience. Arabic quality is not represented by MSA alone, and Egyptian Arabic plus Arabic-English code-switching are important customer language behaviors.

## Decision

English, MSA, Egyptian Arabic, and Arabic-English code-switching are Tier-1 capabilities. Egyptian Arabic and code-switching receive the deepest specialization and evaluation coverage. Gulf and Levantine Arabic remain later evaluation slices. Metrics are always reported per language slice.

## Consequences

Prompts, retrieval judgments, tool-argument labels, voice cases, citations, escalation, and latency reporting must cover the Tier-1 slices. Aggregate quality cannot hide a weak language slice.

## Alternatives considered

- English plus MSA only: rejected because it omits important customer language behavior.
- Support every Arabic dialect equally in V1: rejected because it expands scope beyond evidence and evaluation capacity.
