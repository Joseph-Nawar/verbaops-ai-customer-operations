# ADR-007: Make evaluation and regression measurement first-class

Status: Accepted
Date: 2026-08-19

## Context

Customer-operations quality depends on retrieval, tool selection, typed arguments, conversation behavior, full workflows, voice, safety, latency, and cost. Unversioned demos cannot show whether a change improves or regresses these dimensions.

## Decision

Use versioned evaluation cases and runs at retrieval-query, tool-decision, conversation-turn, full-workflow, and voice-interaction levels. Require separate Tier-1 language slices, honest target reporting, safety zero gates, and regression runs for changes to knowledge, tools, policies, prompts, providers, and voice handling.

## Consequences

Implementation work must preserve trace and version metadata. The project can optimize cost only after measuring a strong-model-only baseline and must not trade away safety or more than two percentage points of task success for the experimental 20% variable-cost reduction target.

## Alternatives considered

- Evaluate only end-to-end demos: rejected because failures cannot be localized or regressed reliably.
- Optimize for aggregate English quality: rejected because it hides Tier-1 language failures.
