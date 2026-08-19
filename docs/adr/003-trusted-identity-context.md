# ADR-003: Identity and tenant context originate from trusted server state

Status: Accepted
Date: 2026-08-19

## Context

User messages and model output are attacker-influenced inputs. Identity, tenant, customer mapping, and roles control access to sensitive data and business actions.

## Decision

The FastAPI API/session layer establishes authenticated principal, tenant, customer association, and role context. That context is passed to the runtime and policy/tool layers as trusted server-side data. Model output and user-supplied tenant/customer identifiers cannot override it.

## Consequences

Every read and write must accept or derive scope from trusted context. Cross-tenant and cross-customer tests are mandatory. Tool arguments may identify a resource, but deterministic authorization must verify that resource against the trusted context.

## Alternatives considered

- Let the model infer identity from conversation: rejected because it is spoofable and ambiguous.
- Trust identifiers supplied by the client without server verification: rejected because identifiers do not prove authorization.
