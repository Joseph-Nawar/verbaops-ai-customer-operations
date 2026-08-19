# RelayAI System Overview

## Purpose and scope

RelayAI is a reusable, tenant-aware customer-operations platform. NovaCommerce is the sole implemented demo tenant: a fictional MENA-oriented consumer-electronics and small-home-technology retailer. Phase 0 defines boundaries and contracts; it does not implement services, databases, providers, or deployment infrastructure.

## Logical architecture

The logical components are:

- Web/text client for customer and agent conversations.
- Admin/approval UI for tenant operations and supervisor decisions.
- FastAPI API/session/trusted-identity layer.
- LiveKit voice ingress and a Voice Worker for streaming transcription/audio turn handling.
- Shared Agent Runtime for conversation orchestration and response generation.
- LLM Gateway/model abstraction for external provider interfaces.
- Retrieval Layer over versioned knowledge documents and chunks.
- Typed Tool Registry exposing only schema-bound operations.
- Deterministic Policy Engine for authorization, eligibility, confirmation, approval, and state-transition rules.
- Separate authenticated NovaCommerce Commerce Sandbox/API, conceptually owning NovaCommerce domain data.
- PostgreSQL for durable RelayAI state and traces.
- Redis for later ephemeral coordination or caching.
- Background worker for asynchronous work.
- Object storage later for larger artifacts.
- Observability and evaluation systems for traces, metrics, regressions, and cost.

## Trust boundaries

The API/session layer is the source of trusted identity, tenant, customer mapping, and roles. The LLM Gateway is an untrusted provider boundary. Retrieved text is evidence, not executable instruction. The Agent Runtime may propose typed tool arguments, but only the Registry, Policy Engine, trusted context, and authenticated Commerce Sandbox/API can authorize or perform business operations.

The Agent Runtime must never directly update NovaCommerce tables. Even when local development later shares PostgreSQL infrastructure, the Commerce Sandbox/API remains the conceptual ownership and access boundary.

## Core request flow

1. A web/text or voice interaction enters through the API/session layer. Voice uses LiveKit and the Voice Worker before entering the shared runtime.
2. The server attaches trusted identity and tenant context; untrusted user/model text cannot replace it.
3. The Agent Runtime retrieves versioned knowledge when needed and asks the LLM Gateway for interpretation, clarification, response composition, or a typed tool proposal.
4. The Tool Registry validates schemas and passes eligible proposals to the deterministic Policy Engine.
5. Reads call the authenticated Commerce Sandbox/API after authorization. Writes additionally require any confirmation or supervisor approval.
6. The result is verified, summarized in the user's language, and recorded with evidence, trace, latency, cost, and audit metadata.
7. Background work, later caching, and later object storage are asynchronous support paths; they do not become authorization boundaries.

## Deployment posture

Phase 0 intentionally chooses a modular service architecture rather than premature microservices. Logical boundaries and interfaces are explicit, but no FastAPI service, container, Kubernetes configuration, cloud resource, provider, queue, or database schema is implemented by this phase. Redis, object storage, and background processing are later capabilities represented in the architecture because they have distinct operational semantics.

## Resilience and observability

Provider and backend failures must produce safe abstention, a retryable state, human handling, or a clear failure response. Writes are idempotent and uncertain writes are reconciled through authenticated reads. Every production agent run is expected to be traceable to tenant/principal context, evidence, model/provider operation, tools, approvals, outcome, latency, and cost. PII is minimized and redacted in logs and evaluation data.

## Related decisions

See ADRs 001–008 for the tenant strategy, trust boundary, identity source, modular architecture, Commerce API boundary, language strategy, evaluation-first development, and provider abstraction.
