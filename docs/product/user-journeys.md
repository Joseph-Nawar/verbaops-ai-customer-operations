# RelayAI User Journeys

These journeys describe the intended Phase 0 behavior. NovaCommerce is the only implemented demo tenant, while every journey assumes trusted tenant-aware server context.

## Customer: information and authenticated read

1. The customer opens a text or browser-voice conversation.
2. The server establishes the authenticated principal, tenant, and optional customer mapping before the Agent Runtime receives the request.
3. For a product, shipping, returns, refund, or warranty question, the runtime retrieves versioned knowledge and answers with citations.
4. If evidence is insufficient or conflicting, the assistant abstains, explains what it cannot establish, and offers clarification or human support.
5. For order, shipment, refund, or return status, the runtime proposes a typed read tool call.
6. Deterministic authorization checks the customer-to-resource relationship before the Commerce Sandbox/API is called.
7. The assistant summarizes the verified result in the customer's language and records the trace.

## Customer: delivery reschedule

1. The customer asks to change delivery timing and identifies the order or provides information for clarification.
2. The runtime proposes a typed order and available-slot lookup.
3. The server validates the proposal and applies customer, tenant, order-state, and slot eligibility rules.
4. The assistant presents the exact order, selected slot, and material consequence for explicit confirmation.
5. After confirmation is bound to the unchanged proposal, the authenticated Commerce Sandbox/API write is invoked with an idempotency key.
6. The result is verified with a follow-up read or authoritative response. Uncertain completion is reported as unresolved and reconciled safely.

## Customer: cancellation or return

1. The customer requests cancellation or a return.
2. The runtime gathers missing order/item details and proposes the typed operation.
3. Deterministic policy evaluates state, eligibility, customer ownership, and risk.
4. An eligible low-risk action requires explicit confirmation. An unusual cancellation or policy exception creates a supervisor approval request instead.
5. A return request includes the selected return items and a validated reason. It is not executed from free-form model text.
6. The platform invokes the authenticated Commerce Sandbox/API, verifies the result, and communicates the outcome with a trace reference.

## Customer: support ticket and failure

1. The customer asks for help that is unsupported, ambiguous, or not resolved by policy evidence.
2. The assistant asks a focused clarification when clarification can resolve the request.
3. If a ticket is appropriate, it shows a typed summary, category, and target customer context before creation.
4. The ticket write is idempotent; safe retry or reconciliation prevents duplicate tickets.
5. Nonexistent resources, unauthorized requests, backend unavailability, insufficient evidence, and unsupported capabilities receive distinct, non-sensitive explanations.

## Human support agent: assisted resolution

1. The support agent opens a tenant-scoped queue or customer conversation.
2. Trusted server context supplies the agent role and tenant; the model cannot elevate the role or switch tenants.
3. The agent reviews cited knowledge, verified commerce reads, proposed tool arguments, and policy results.
4. The agent may continue the conversation, request clarification, or execute an allowed action after required customer confirmation.
5. High-risk proposals are routed to an authorized supervisor. Every proposal, approval, tool call, and outcome is auditable.

## Supervisor/approver: human-controlled action

1. A high-value refund, unusual cancellation, or policy exception produces an approval request containing the exact typed proposal, evidence, risk reason, tenant, customer, target, and expiry.
2. The supervisor reviews the request in the approval UI and accepts or rejects it using their authenticated principal.
3. Approval is bound to the immutable proposal and cannot be replayed for another target, tenant, or changed amount.
4. The server rechecks authorization, policy, freshness, and idempotency at execution time.
5. The Commerce Sandbox/API is called only after the checks pass, and the verified outcome is written to the audit trail.

## Tenant AI/operations administrator

1. The administrator reviews tenant-scoped knowledge document versions, evaluation cases/runs, traces, language slices, latency, and cost.
2. The administrator can inspect divergences and audit events without receiving data outside the tenant scope.
3. Knowledge changes are versioned so retrieval and evaluation results remain attributable.
4. The administrator cannot use model instructions, configuration text, or UI controls to bypass deterministic authorization, confirmation, approval, or audit rules.

## Browser voice: interruption and final-turn gate

1. Browser audio streams to LiveKit and the Voice Worker, which produces partial and final transcript events for the shared Agent Runtime.
2. Partial transcripts may drive conversational feedback but cannot trigger a business write.
3. If the customer interrupts, the current response is stopped or marked interrupted and no pending action is treated as confirmed.
4. The final transcript is interpreted into a typed proposal and passes schema, policy, and authorization checks.
5. For a write, the system communicates the action summary and waits for an explicit final confirmation or human approval.
6. Only the confirmed final turn may invoke the typed authenticated business API; the verified result is then spoken and recorded.
