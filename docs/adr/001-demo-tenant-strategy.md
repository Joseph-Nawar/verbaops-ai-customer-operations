# ADR-001: NovaCommerce is the only implemented demo tenant

Status: Accepted
Date: 2026-08-19

## Context

RelayAI is intended to be reusable across customer-operations tenants, but Phase 0 needs one coherent business domain for demonstrations and evaluation. NovaCommerce supplies that domain as a fictional MENA-oriented retailer.

## Decision

Implement only NovaCommerce as the demo tenant while keeping the platform model tenant-aware. The documentation, records, policies, knowledge, and evaluation cases must distinguish platform concepts from NovaCommerce-owned commerce concepts.

## Consequences

Evaluation can be concrete without implying that integrations with real retailers exist. Tenant scoping, identity, authorization, and data relationships are designed for reuse. NovaCommerce remains a fictional Commerce Sandbox/API boundary, not a real payment, courier, or CRM integration.

## Alternatives considered

- Build multiple demo tenants: rejected because it expands Phase 0 scope and dilutes domain-specific evaluation.
- Make RelayAI NovaCommerce-specific: rejected because it prevents the intended reusable platform architecture.
