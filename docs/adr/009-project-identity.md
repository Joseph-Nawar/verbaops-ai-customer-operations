# ADR-009: Project Identity

**Status:** Accepted

## Context

The original working name RelayAI was useful during Phase 0/Stage 1 development but was insufficiently descriptive and distinctive for recruiter-facing publication. The repository had not yet been published and had no external consumers, making this the safest point for a complete identity migration.

## Decision

Rename the product to:

**VerbaOps AI**

with:

- repository = `verbaops-ai-customer-operations`
- distribution = `verbaops-ai`
- import package = `verbaops`
- environment namespace = `VERBAOPS_`
- service identifier = `verbaops`

NovaCommerce remains unchanged.

## Consequences

- Current source, configuration, documentation, and tests use the VerbaOps identity.
- Historical Git commits are not rewritten.
- Architecture, security boundaries, workflows, evaluation targets, and product scope are unchanged.
- Future recruiter-facing materials use the new identity.

## Alternatives considered

- Retain RelayAI.
- Use only a descriptive generic repository name.
- Rename the public project while keeping `relayai` internally.

A complete internal rename was chosen because there are no external consumers requiring backwards compatibility.
