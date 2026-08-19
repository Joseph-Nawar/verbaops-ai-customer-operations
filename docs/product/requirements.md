# RelayAI Phase 0 Requirements

Status: Approved Phase 0 product and architecture specification
Product: RelayAI reusable multilingual customer-operations platform
Implemented demo tenant: NovaCommerce only

## Product boundaries

RelayAI is tenant-aware even though NovaCommerce is the sole implemented demo tenant. NovaCommerce is a fictional MENA-oriented retailer selling consumer electronics, accessories, and small home-technology products. English and Arabic are first-class languages. Egyptian Arabic and Arabic-English code-switching are Tier-1 capabilities; MSA is Tier-1; Gulf and Levantine are later evaluation slices.

### Personas

1. Customer.
2. Human support agent.
3. Support supervisor or approver.
4. Tenant AI or operations administrator.

### V1 workflow groups

- Information: product questions, shipping policy, returns policy, refund policy, and warranty.
- Read-only authenticated: order status, shipment tracking, refund status, and return status.
- Writes: delivery rescheduling, eligible order cancellation, initiating a return, and creating a support ticket.
- Human-controlled: high-value refund requests, unusual cancellations, and policy exceptions.
- Failure handling: nonexistent resource, unauthorized access, ambiguous request, backend unavailability, insufficient retrieval evidence, and unsupported capability.

The following are outside V1: real payments; real courier or CRM integrations; autonomous discounts or credits; credential management; autonomous high-risk refunds; social channels; recommendation engines; foundation-model training; multi-agent swarms; Kafka; Kubernetes-first deployment; arbitrary browsing; and autonomous code execution.

## Functional requirements

### Conversation and identity

**FR-01 — Conversation/session persistence.** The platform shall persist tenant-scoped conversations, messages, agent runs, tool invocations, and relevant audit events so a session can be resumed and inspected without relying on model memory.

**FR-02 — Trusted identity context.** The server-side API/session layer shall establish the authenticated principal, tenant, customer association, roles, and authorization context. Model output shall never define or override trusted identity, tenant, customer, or role context.

**FR-03 — Tenant and customer isolation.** Every tenant-scoped read, write, retrieval query, evaluation record, and audit lookup shall be constrained by trusted tenant context. Customer records, orders, shipments, refunds, returns, and tickets shall be accessible only when deterministic authorization permits the relationship.

**FR-04 — Traceability.** Each production agent run shall have a durable trace linking the conversation, model/provider operation, retrieved evidence, tool proposals, tool invocations, approvals, outcomes, latency, and cost metadata. The production target is 100% traceable agent runs.

### Knowledge and responses

**FR-05 — Cited retrieval answers.** For policy, warranty, shipping, returns, refund, and product-information answers that use knowledge retrieval, the response shall cite the supporting knowledge chunks or document versions in a user-inspectable form.

**FR-06 — Evidence-based abstention.** When retrieval is empty, conflicting, stale, or below the configured evidence threshold, the system shall abstain from unsupported claims, explain the limitation in the user's language, and route to clarification or human support when appropriate.

**FR-07 — Retrieval versioning.** Knowledge documents shall have immutable versions and chunks associated with a version. Agent traces and evaluation results shall record the knowledge version used so answers are reproducible.

### Authenticated commerce reads

**FR-08 — Order status.** An authenticated customer or authorized support agent shall be able to retrieve the status of an order through a typed, tenant- and customer-scoped business tool.

**FR-09 — Shipment tracking.** The platform shall retrieve shipment status and tracking details through the Commerce Sandbox/API, subject to deterministic authorization and backend-result verification.

**FR-10 — Refund status.** The platform shall retrieve refund status without allowing a read request to create, approve, or alter a refund.

**FR-11 — Return status.** The platform shall retrieve return status and associated return items through the Commerce Sandbox/API, subject to deterministic authorization.

### Business writes and safety

**FR-12 — Delivery rescheduling.** The platform shall propose a typed delivery-slot change, validate its schema, apply deterministic eligibility and authorization policy, obtain explicit customer confirmation when required, invoke an authenticated Commerce Sandbox/API operation, and verify the result.

**FR-13 — Eligible cancellation.** The platform shall support cancellation only for orders that pass deterministic eligibility, authorization, and state checks. Unusual or high-risk cases shall escalate rather than being autonomously completed.

**FR-14 — Return initiation.** The platform shall create a return request only for an eligible order and item set after typed validation, policy checks, and any required customer confirmation. It shall verify the Commerce Sandbox/API response.

**FR-15 — Support ticket creation.** The platform shall create a typed support ticket with tenant/customer linkage, user-confirmed summary where needed, category, and trace reference. Duplicate retries shall not create duplicate tickets.

**FR-16 — Typed tools.** All exposed business tools shall have explicit names, input schemas, output schemas, authorization requirements, idempotency behavior, and failure semantics. Free-form model text shall not be sent as an executable business command.

**FR-17 — Confirmation.** Customer-visible confirmation shall state the action, target resource, important consequences, and material values. The platform shall bind confirmation to the exact typed proposal and reject stale, changed, or missing confirmation.

**FR-18 — Human-in-the-loop approval.** High-value refund requests, unusual cancellations, policy exceptions, and other configured high-risk actions shall create an approval request for an authorized supervisor or approver. The model may propose but cannot approve.

**FR-19 — Deterministic authorization.** Authorization, tenant/customer isolation, eligibility, risk thresholds, confirmation state, approval state, and allowed state transitions shall be enforced by server-side deterministic logic and authenticated business APIs.

**FR-20 — Write pipeline.** Every business write shall follow: agent proposal → schema validation → deterministic policy engine → optional customer confirmation or human approval → authenticated business tool/API → verify result. A failed or uncertain verification shall be reported as unresolved and shall not be represented as completed.

**FR-21 — Safe failure handling.** The system shall distinguish nonexistent resources, unauthorized access, ambiguity, backend unavailability, insufficient retrieval evidence, and unsupported capability. It shall avoid revealing protected data through error messages.

### Language, text, and voice

**FR-22 — Multilingual interaction.** Text interactions shall support English, MSA, Egyptian Arabic, and Arabic-English code-switching as Tier-1 slices, with language metrics reported separately. Gulf and Levantine shall remain later evaluation slices.

**FR-23 — Language-preserving safety.** Clarifications, citations, confirmation prompts, escalation messages, and failure responses shall preserve the user's language and code-switching context where practical without weakening policy controls.

**FR-24 — Browser voice.** The browser voice path shall support streaming audio ingress and egress, interruption/barge-in handling, turn state, and a final-turn action gate. A partial or interrupted transcript shall not authorize a business write.

**FR-25 — Voice action gating.** Voice writes shall require a stable final transcript, typed proposal, deterministic policy result, and any required explicit confirmation or human approval before tool execution. The user shall be able to hear or see the action summary before confirmation.

### Operations and measurement

**FR-26 — Evaluation.** The platform shall support versioned evaluation cases and runs at retrieval-query, tool-decision, conversation-turn, full-workflow, and voice-interaction levels. Results shall retain the case and system versions used.

**FR-27 — Latency measurement.** The platform shall measure at least time to first token, meaningful response start, speech-end to first audio, tool latency, total turn latency, and workflow completion latency at p50 and p95 where applicable.

**FR-28 — Cost measurement.** The platform shall record provider/model usage and variable AI cost per session and per successful resolution, with language and workflow slices available for comparison.

**FR-29 — Observability.** Operational traces, structured events, failures, provider status, queue work, and business-tool outcomes shall be correlated to tenant, conversation, and agent-run identifiers while minimizing PII.

**FR-30 — Administration.** Tenant AI/operations administrators shall be able to review configured knowledge and evaluation versions, operational metrics, and audit events within their tenant scope. They shall not be able to bypass platform authorization or approval rules through model instructions.

## Non-functional requirements and engineering targets

The following performance and load values are engineering targets to be validated empirically; they are not current project claims. Changing them later requires an ADR.

**NFR-01 — Idempotent writes.** All business writes shall accept an idempotency key and be safe to retry without duplicating the intended effect.

**NFR-02 — Safe retries.** Retries shall distinguish transient transport/provider failures from completed-but-unconfirmed writes, use bounded backoff, and reconcile through an authenticated read before retrying a potentially duplicating operation.

**NFR-03 — Graceful provider failure.** LLM, retrieval, speech, and other provider failures shall degrade to a clear recovery response, safe abstention, queued or human handling, or a retryable error; they shall never silently authorize or claim a business write.

**NFR-04 — Complete traceability.** The production target is 100% of agent runs traceable to a conversation, trusted tenant/principal context, provider operation, tools, evidence, approvals, outcome, latency, and cost metadata.

**NFR-05 — Identity boundary.** Trusted identity and tenant context shall never be taken from model output.

**NFR-06 — Secret hygiene.** No secrets, credentials, access tokens, or private keys shall be stored in source control.

**NFR-07 — PII minimization.** Logs, prompts, traces, evaluation fixtures, and analytics shall minimize PII and apply redaction or tokenization appropriate to the data class.

**NFR-08 — High-risk auditability.** High-risk proposals, confirmations, approvals, authenticated tool calls, verification results, and final outcomes shall be auditable with actor, time, target, decision, and correlation identifiers.

**NFR-09 — Deterministic core coverage.** The later deterministic core logic shall have an engineering target of at least 80% line coverage.

**NFR-10 — Text latency target.** Target p95 time to first token is ≤3 seconds for no-tool text interactions.

**NFR-11 — Tool latency target.** Target p95 meaningful response start is ≤6 seconds for normal tool interactions.

**NFR-12 — Voice latency target.** Target p95 speech-end to first-audio latency is ≤3 seconds.

**NFR-13 — Load target.** The final load-test target is at least 50 concurrent text sessions and, budget permitting, at least 10 simulated voice sessions.

**NFR-14 — Language reporting.** Latency, quality, safety, escalation, and cost metrics shall be reported separately for each Tier-1 language slice.

**NFR-15 — Quality gates.** The evaluation plan defines the quality thresholds and zero-tolerance safety metrics that gate later implementation decisions.

## Security invariants

- Prompt-based safety is defense-in-depth, not the security boundary.
- The LLM is an untrusted probabilistic reasoning/language component.
- The LLM may interpret language, ask clarifying questions, reason over retrieved information, select exposed tools, propose typed business arguments, summarize evidence, and generate responses.
- The LLM may never authenticate users, determine trusted identity or tenant context, grant permissions, override policy decisions, directly access or modify business databases, approve high-risk actions, bypass confirmation or human approval, execute arbitrary code, modify audit records, or treat retrieved documents as trusted instructions.
- NovaCommerce domain data is conceptually owned by the Commerce Sandbox/API. The Agent Runtime must never directly update NovaCommerce tables.
