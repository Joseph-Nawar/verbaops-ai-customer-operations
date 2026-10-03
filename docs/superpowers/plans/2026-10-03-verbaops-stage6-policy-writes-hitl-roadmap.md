# VerbaOps Stage 6 — Policy + Writes + Confirmation + HITL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver Stage 6 as seven independently reviewable milestones that add durable, deterministic, customer-confirmed Commerce actions with narrowly scoped supervisor approval and verified outcomes.

**Architecture:** VerbaOps owns typed proposals, policy gates, durable action state, actor decisions, execution orchestration, and verification. NovaCommerce remains the authority for eligibility and transactional writes. Model tools can create proposals only; actor operations and a private executor advance the lifecycle.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLAlchemy async, Alembic, PostgreSQL, HTTPX, pytest, Next.js 16, React 19, Vitest, and Playwright.

**Spec:** docs/superpowers/specs/2026-10-02-verbaops-stage6-policy-writes-hitl-design.md at approved commit 58cdab65b73b95bfd3c5299214ef901e1427a545.

## Global Constraints

### Trust boundary

- Model proposes only.
- Model never authorizes.
- Model never confirms.
- Model never approves.
- Model never executes Commerce writes directly.
- Model never verifies success.

### Identity

Trusted context alone supplies:

- principal;
- tenant;
- customer;
- roles.

Never accept those values from model, tool, or browser payloads.

### Commerce ownership

NovaCommerce remains authoritative for:

- customer ownership;
- business eligibility;
- transactional writes;
- locking;
- idempotency;
- Commerce events.

VerbaOps never directly mutates Commerce tables.

### Stage 5 boundary

Stage 5 remains:

NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE

Stage 6 must not promote P0–P5 or depend on experimental RAG to authorize writes.

### Frozen action gates

All five actions require explicit customer confirmation. Supervisor approval is conditional exactly as shown; all other eligible states have no supervisor gate.

| Action | Customer confirmation | Supervisor approval |
|---|---|---|
| Reschedule | Required | Never required in the initial policy, including Commerce-eligible IN_TRANSIT |
| Cancellation | Required | Only for otherwise-eligible PROCESSING orders and/or LABEL_CREATED shipments |
| Return | Required | Not required when eligible |
| Support ticket | Required | Not required for ordinary tickets |
| Refund | Required | Only when amount is greater than 500.00 in trusted tenant currency |

Exactly 500.00 does not require supervisor approval.

### Durable workflow

- action_requests is the authoritative current action state.
- action_events is append-only, bounded audit history; this is not event sourcing.
- Use only the approved states: proposed, policy_denied, awaiting_approval, awaiting_confirmation, ready_to_execute, executing, succeeded, rejected, failed, unresolved, expired.
- Do not add a generic workflow engine, BPM, Temporal, Kafka, or policy DSL.
- One transition service owns legal state changes. State and event commit atomically.
- Supervisor approval precedes customer confirmation whenever both are required.
- No public execute endpoint or generic set-state endpoint.
- A single stable idempotency key belongs to each action; retries and reconciliation reuse it.
- Only an exact expected postcondition may produce succeeded. unresolved remains non-terminal and non-success.

### Other fixed boundaries

- No production identity-provider/session project and no full voice implementation. Preserve exact customer confirmation so partial/interrupted transcripts cannot authorize an action later.
- No multi-currency, browser/model currency choice, payment movement, unrelated ticket changes, historical migration edits, provider calls, or Stage 5 redesign.
- Each milestone begins on a fresh branch from updated main; no implementation branch is created during roadmap work.

## Review Focus

1. Ambiguous timeout after a Commerce write may have dispatched: exact read-back first, then safe same-key replay, otherwise unresolved. Owning test: tests/actions/test_executor.py — test_read_timeout_after_dispatch_reconciles_with_same_key_or_stays_unresolved.
2. Confirmation or approval replay after a material proposal/snapshot change: old fingerprint conflicts and cannot execute. Owning test: tests/actions/test_decisions.py — test_stale_fingerprint_cannot_replay_confirmation_or_approval, implemented across M6D confirmation and M6E approval.
3. Concurrent duplicate execution: one locked claim and at most one distinct Commerce write. Owning test: tests/postgres/stage6/test_execution_concurrency.py — test_two_workers_claim_one_action_and_dispatch_once in M6D.2.
4. Supervisor self-approval: proposer principal cannot approve their own action, even if they hold support_supervisor. Owning test: tests/api/test_action_requests.py — test_proposer_cannot_approve_own_action.
5. Cross-customer action-ID enumeration: random and other-customer IDs have the same non-enumerating not-found response and no side effect. Owning test: tests/api/test_action_requests.py — test_cross_customer_action_id_matches_random_id_not_found.

## Repository audit and ownership map

Audit completed on stage6/policy-writes-hitl-planning at the approved spec head. The branch was clean and contained only the approved Stage 6 specification.

| Area | Existing seam | Planned ownership |
|---|---|---|
| VerbaOps persistence | src/verbaops/db/base.py; src/verbaops/conversations/persistence.py; migrations/env.py imports models; migrations end at 0005_retrieval_grounding_v1 | New src/verbaops/actions/persistence.py and 0006_action_lifecycle_v1.py; import action metadata from migrations/env.py |
| VerbaOps runtime | src/verbaops/api/lifespan.py creates CommerceClient, ConversationService, AgentRuntime; src/verbaops/api/dependencies.py exposes runtime services | Add ActionService and ActionExecutor to lifespan-owned RuntimeResources and narrow dependency getters |
| Identity | src/verbaops/auth/context.py defines frozen TrustedContext; API obtains it through get_trusted_context; development contexts are server-mapped | Pass complete TrustedContext into proposal handlers and actor APIs; never add identity fields to payloads |
| Agent/tools | src/verbaops/tools/registry.py builds the read-only registry; src/verbaops/agent/graph.py executes tools; ToolInvocation is appended after handler execution | Register proposal tools only; begin a trace before execution and finish it afterward so action_requests references a durable ToolInvocation ID |
| NovaCommerce | Separate SQLAlchemy metadata, alembic-commerce.ini and commerce_migrations/versions/0001_create_commerce_schema.py; existing writes use typed routes, service auth, idempotency, and transactions | Add only ticket category, exact-resource reads, trusted currency metadata, and refund approval-reference behavior |
| Commerce gaps | SupportTicket has no category; returns/tickets lack exact-resource GET; Settings has no canonical tenant currency; refunds above 500.00 currently become pending manual approval | Fill these contract gaps without changing unrelated Stage 2 behavior |
| Web | apps/web has server-only BFF apps/web/src/lib/server/verbaops.ts, conversation routes, and read-only chat; production browser sessions are not implemented | Add narrowly validated action BFF routes and minimal proposal/decision views; keep credentials server-side and production sessions out of scope |
| Tests and CI | pytest uses postgres, contract, concurrency, critical_race markers; apps/web uses Vitest/Playwright; .github/workflows/ci.yml has quality, Postgres, Commerce, and web jobs | Add provider-free Stage 6 contract, persistence/concurrency, and black-box acceptance gates by extending existing jobs or adding only milestone-sized jobs |

## Dependency order

M6A → M6B → M6C → M6D → M6E → M6F → M6G.

M6A freezes VerbaOps types, policy, persistence, and transitions. M6B completes the independent Commerce contract before any action tool depends on it. M6C records proposals without writes. M6D adds customer-controlled execution for no-approval paths. M6E adds the two supervisor workflows on the stable execution path. M6F integrates durable states into the agent and browser. M6G proves the whole workflow and locks permanent CI. Each milestone merges before the next branch starts from updated main.

## Frozen cross-milestone interfaces

- ActionType values are reschedule_delivery, cancel_order, initiate_return, create_support_ticket, request_refund. Proposal classes have a Literal action_type plus strict typed fields: reschedule(order_id, delivery_slot_id); cancel(order_id); return(order_id, distinct item/quantity tuple, reason); ticket(optional order_id, required category, subject, description); refund(order_id, positive Decimal amount, reason). Model inputs contain no identity or gate fields.
- ActionState is exactly the eleven states in Global Constraints. The only edges are: proposed→policy_denied/awaiting_approval/awaiting_confirmation/ready_to_execute/failed/expired; awaiting_approval→awaiting_confirmation/ready_to_execute/rejected/expired; awaiting_confirmation→ready_to_execute/rejected/expired; ready_to_execute→executing/policy_denied/expired; executing→succeeded/failed/ready_to_execute only for proven non-dispatch retry/unresolved; unresolved→executing/succeeded/failed/unresolved. policy_denied, rejected, succeeded, failed, expired are terminal.
- PolicyDecision fields are allowed: bool, reason_code: str, confirmation_required: bool, approval_required: bool, policy_version: str. evaluate_action_policy(trusted_context: TrustedContext, proposal: ActionProposal, commerce_snapshot: CommerceSnapshot, canonical_currency: str | None, policy_version: str) -> PolicyDecision is pure.
- fingerprint_proposal(tenant_id: UUID, customer_id: UUID, action_type: ActionType, schema_version: str, target_ids: tuple[UUID, ...], normalized_payload: dict[str, JSONValue], material_snapshot: dict[str, JSONValue]) -> str returns lowercase SHA-256 hex over a domain/version-prefixed deterministic envelope. UUIDs, Decimal values, UTC timestamps, enums, and object keys have one canonical representation. Include material preflight values; exclude secrets, prompts, action ID, and approval/confirmation decisions.
- ActionRequestSummary(action_request_id: UUID, action_type: ActionType, state: ActionState, proposal_fingerprint: str, safe_summary: str, required_next_actor: Literal['customer','support_supervisor','none']). ActionProposalService.propose(trusted_context: TrustedContext, conversation_id: UUID, agent_run_id: UUID, tool_invocation_id: UUID, proposal: ActionProposal) -> ActionRequestSummary reads scoped Commerce facts, resolves currency for refunds, evaluates policy, fingerprints, deduplicates, and records request plus event.
- ActionTransitionService.transition(action_request_id: UUID, tenant_id: UUID, expected_fingerprint: str, target_state: ActionState, actor_id: UUID | None, event_type: ActionEventType, reason_code: str | None) -> ActionRequestRecord locks the request, validates state/fingerprint/expiry, and commits state plus bounded event atomically.
- ToolExecutionContext(trusted_context: TrustedContext, conversation_id: UUID, agent_run_id: UUID, tool_invocation_id: UUID). Model-visible fields remain only action payload.
- CommerceClient keeps typed fixed-path methods: get_return(return_id: UUID, customer_id: UUID) -> ReturnResponse; get_support_ticket(ticket_id: UUID, customer_id: UUID) -> SupportTicketResponse; get_tenant_currency() -> TenantCurrencyResponse; cancel_order(order_id: UUID, customer_id: UUID, idempotency_key: UUID) -> OrderResponse; reschedule_delivery(order_id: UUID, customer_id: UUID, delivery_slot_id: UUID, idempotency_key: UUID) -> ShipmentResponse; create_return(customer_id: UUID, request: ReturnCreateRequest, idempotency_key: UUID) -> ReturnResponse; create_support_ticket(customer_id: UUID, request: SupportTicketCreateRequest, idempotency_key: UUID) -> SupportTicketResponse; request_refund(order_id: UUID, customer_id: UUID, request: RefundCreateRequest, approval_reference: RefundApprovalReference | None, idempotency_key: UUID) -> RefundResponse. No URL/path argument. Read retries never apply to writes. Writes use trusted customer ID and stable idempotency key; refund approval reference is constructed only from the stored action approval.
- ActionExecutor.execute_ready(action_request_id: UUID) -> ActionRequestRecord is internal. ActionReconciler.reconcile(action_request_id: UUID, trusted_context: TrustedContext) -> ActionRequestRecord reads back first and may replay only the identical operation with the same key under the NovaCommerce idempotency contract.
- Actor endpoints use the exact GET/POST route shapes above and bind action ID/fingerprint to authenticated TrustedContext. No payload can set tenant, principal, customer, role, lifecycle state, gate result, currency, or idempotency key.

## Milestone closeout gate

Every milestone ends with focused tests green; relevant regressions; whole-milestone security/scope review; git diff --check; only intended files changed; clean worktree; commit(s); push; hosted CI green on exact head; independent review; merge. Do not start the next milestone until main contains the reviewed milestone. Never stack M6A–M6G on one implementation branch.

# M6A — Durable action domain and deterministic policy foundation

**Branch:** stage6/m6a-action-lifecycle
**Deliverable:** VerbaOps represents, fingerprints, evaluates, persists, transitions, expires, and audits proposals without a write executor or provider call.

### Task M6A.1 — Typed contracts and fingerprints

**Files**
- Create: src/verbaops/actions/__init__.py, src/verbaops/actions/models.py, src/verbaops/actions/fingerprints.py
- Test: tests/actions/__init__.py, tests/actions/test_models.py, tests/actions/test_fingerprints.py

**Interfaces**
- Produces ActionType, ActionState, ActionGate, RescheduleDeliveryProposal, CancelOrderProposal, ReturnProposal, SupportTicketProposal, RefundProposal, discriminated ActionProposal, CommerceSnapshot, and the typed fingerprint_proposal signature frozen above.
- Decimal amounts use fixed-scale strings. VerbaOps defines the same closed ticket-category values as NovaCommerce and verifies wire-value equality without importing Commerce persistence models. No identity, gate, execution, currency-choice, or approval-reference field is a proposal input.

- [ ] RED: Add test_action_payloads_forbid_identity_and_unknown_fields, test_fingerprint_is_stable_for_equivalent_normalized_inputs, and test_fingerprint_changes_for_scope_action_schema_payload_or_snapshot. Run uv run pytest tests/actions/test_models.py tests/actions/test_fingerprints.py -q; expected RED on missing interfaces/assertions.
- [ ] GREEN: Implement strict value models and deterministic canonical envelope/digest.
- [ ] Verify: Re-run tests, uv run ruff check src/verbaops/actions tests/actions, and uv run mypy src/verbaops/actions tests/actions.
- [ ] Commit: feat: define durable action contracts.

### Task M6A.2 — Pure action policy and frozen gates

**Files**
- Create: src/verbaops/actions/policy.py, tests/actions/test_policy.py

**Interfaces**
- Consumes TrustedContext, ActionProposal, CommerceSnapshot, canonical currency or None, and policy version.
- Produces evaluate_action_policy(...) -> PolicyDecision with stable reason codes and required gates; no I/O or mutation.

- [ ] RED: Test customer scope, support-agent/supervisor proposals only with a server-bound customer, tenant-admin-only denial, confirmation on all actions, IN_TRANSIT reschedule with no supervisor, cancellation PROCESSING/LABEL_CREATED, return/ticket normal paths, stale/fresh snapshots, and refunds 499.99/500.00/500.01. Run uv run pytest tests/actions/test_policy.py -q; expected RED on policy behavior.
- [ ] GREEN: Implement explicit per-action policy functions and typed decision. Missing currency denies refund before confirmation.
- [ ] Verify: Re-run tests and Ruff on action policy.
- [ ] Commit: feat: add deterministic action policy.

### Task M6A.3 — VerbaOps tables and additive migration

**Files**
- Create: src/verbaops/actions/persistence.py, migrations/versions/0006_action_lifecycle_v1.py, tests/migrations/test_action_lifecycle_migration.py
- Modify: migrations/env.py
- Test: tests/postgres/stage6/conftest.py

**Interfaces**
- action_requests stores scope/proposer/conversation/run/ToolInvocation links, strict payload, schema/policy versions, fingerprint, state, gate requirements/decisions, one stable key, expiry, execution lease/version, and bounded response/verification metadata.
- action_events stores event/action/tenant IDs, actor/time, previous/next states, fingerprint, correlation IDs, and bounded reason. It never duplicates prompts, credentials, raw Commerce bodies, ticket text, or reasons.
- Register new metadata through migrations/env.py and the existing VerbaOps Base. Add a database trigger that rejects UPDATE and DELETE on action_events; expose no application update/delete operation. Do not edit historical migrations.

- [ ] RED: Test exact columns/checks, scoped indexes, unique origin invocation, active-request uniqueness, and database rejection of event UPDATE/DELETE. Run uv run pytest tests/migrations/test_action_lifecycle_migration.py -q; expected RED before revision 0006.
- [ ] GREEN: Add 0006_action_lifecycle_v1 after 0005_retrieval_grounding_v1 with reversible constraints/indexes and restrictive event FK.
- [ ] Verify: Run migration tests and uv run alembic upgrade head on an isolated VerbaOps test DB.
- [ ] Commit: feat: add action lifecycle schema.

### Task M6A.4 — Atomic repository, transitions, deduplication, expiry

**Files**
- Create: src/verbaops/actions/repository.py, src/verbaops/actions/transitions.py, tests/actions/test_transitions.py
- Test: tests/postgres/stage6/test_action_repository.py, tests/postgres/stage6/test_action_concurrency.py

**Interfaces**
- ActionRepository.create_or_get(*, trusted_context: TrustedContext, conversation_id: UUID, agent_run_id: UUID, tool_invocation_id: UUID, proposal: ActionProposal, proposal_fingerprint: str, expires_at: datetime) -> tuple[ActionRequestRecord, bool] inserts proposed request plus created event atomically; identical active tenant/conversation/customer/fingerprint returns the existing request.
- ActionTransitionService.transition(...) is the only state mutator. It locks, checks transition/fingerprint/expiry/version, then updates row and event in one transaction.
- Unique origin invocation creates at most one action. A changed active proposal with same conversation/customer/action/targets expires the older undispatched request as superseded. Different action/targets remain independent. Terminal requests allow a new ID/key.
- Generate and store one random UUID idempotency key at creation. Expiry is 24 hours; checks share the lock with gate/claim operations. Dispatched/unresolved work remains reconcilable.

- [ ] RED: Test invalid transition, atomic event, duplicate invocation, active identical dedup, changed-proposal supersession, terminal fresh action, expiry race, and concurrent create. Run uv run pytest tests/actions/test_transitions.py -q and uv run pytest tests/postgres/stage6/test_action_repository.py tests/postgres/stage6/test_action_concurrency.py -m "postgres and contract" -q; expected RED before repository exists.
- [ ] GREEN: Implement transaction-owning repository and transition operations; resolve unique conflicts by loading the winning scoped request.
- [ ] Verify: Re-run focused and VerbaOps PostgreSQL tests; assert one event per transition.
- [ ] Commit: feat: persist and transition action requests.

**M6A acceptance/stop:** Policy is pure-testable, migration upgrades from 0005, state changes are serialized/audited, and no executor or proposal tool exists. Merge only after milestone closeout.

# M6B — NovaCommerce Stage 6 contract completion

**Branch:** stage6/m6b-commerce-contracts
**Deliverable:** Commerce gains only ticket category, exact read-back, trusted tenant currency, and bound refund evidence required by the spec.

### Task M6B.1 — Support-ticket category

**Files**
- Modify: src/novacommerce/db/models/support_ticket.py, src/novacommerce/schemas/writes.py, src/novacommerce/services/writes/tickets.py
- Create: commerce_migrations/versions/0002_stage6_ticket_category.py, tests/novacommerce/test_stage6_ticket_category.py
- Modify: tests/novacommerce/test_m2d_schemas.py, tests/integration/test_m2d_write_postgres.py, contracts/novacommerce-openapi.json

**Interfaces**
- SupportTicketCategory is exactly order, delivery, returns_refunds, product, warranty, payment, account, other.
- Existing Commerce clients may omit category and receive compatibility default other; Stage 6 proposal input requires a category. Persist/return stable key and include it in support_ticket.created event metadata.
- Migration adds non-null category with default other for existing rows. No unrelated ticket behavior changes.

- [ ] RED: Test closed values, persistence/response/event round-trip, and legacy default. Run uv run pytest tests/novacommerce/test_stage6_ticket_category.py -q; expected RED before enum/schema.
- [ ] GREEN: Implement enum, request/response/model/event and additive Commerce migration.
- [ ] Verify: Run ticket schema/service/PostgreSQL tests and make commerce-contract-check after make commerce-contract-update.
- [ ] Commit: feat: add support ticket categories.

### Task M6B.2 — Exact return and ticket reads

**Files**
- Modify: src/novacommerce/api/v1/router.py, src/novacommerce/schemas/writes.py
- Create: src/novacommerce/api/v1/read_returns.py, src/novacommerce/api/v1/read_tickets.py, tests/novacommerce/test_stage6_exact_reads.py
- Modify: contracts/novacommerce-openapi.json

**Interfaces**
- GET /v1/returns/{return_id} returns exact ReturnResponse only when customer_dependency matches owner.
- GET /v1/support-tickets/{ticket_id} returns exact SupportTicketResponse including category only for the owner.
- Missing and other-customer IDs return the same non-enumerating 404. No list/search/export endpoint.

- [ ] RED: Test exact-ID round-trip, missing/other-owner equivalence, and OpenAPI route shape. Run uv run pytest tests/novacommerce/test_stage6_exact_reads.py -q; expected RED on absent GET routes.
- [ ] GREEN: Add two scoped GET handlers to the v1 router.
- [ ] Verify: Run Commerce API/PostgreSQL tests and make commerce-contract-check.
- [ ] Commit: feat: add exact action verification reads.

### Task M6B.3 — Canonical currency and refund approval contract

**Files**
- Modify: src/novacommerce/config/settings.py, src/novacommerce/api/v1/dependencies.py, src/novacommerce/api/v1/router.py, src/novacommerce/schemas/writes.py, src/novacommerce/services/writes/refunds.py, src/novacommerce/services/writes/rules.py
- Create: src/novacommerce/api/v1/tenant_currency.py, tests/novacommerce/test_stage6_refunds.py
- Modify: tests/novacommerce/test_settings.py, tests/integration/test_m2d_write_postgres.py, contracts/novacommerce-openapi.json

**Interfaces**
- NovaCommerce Settings.tenant_currency is the sole trusted source, loaded from NOVACOMMERCE_TENANT_CURRENCY as uppercase three-letter code; it has no guessed default.
- Authenticated service-only GET /v1/tenant-config/currency returns TenantCurrencyResponse(currency_code). Missing configuration returns a stable sanitized unavailable response. VerbaOps reads it through CommerceClient before refund confirmation rather than keeping a duplicate currency.
- RefundApprovalReference(action_request_id: UUID, proposal_fingerprint: str) is constructed only from a stored approved action. Only authenticated internal writes provide it; include it in the Commerce write fingerprint and event metadata, never in model/browser payload.
- Commerce independently applies amount > 500.00. Above threshold without a valid reference is no-mutation rejection; with the reference it creates approved while requires_manual_approval stays true. At/below threshold needs no reference. No payment movement.

- [ ] RED: Test setting/absence, 499.99/500.00/500.01, missing/valid/malformed reference, no mutation, remaining-refundable denial, and replay. Run uv run pytest tests/novacommerce/test_stage6_refunds.py tests/novacommerce/test_settings.py -q; expected RED.
- [ ] GREEN: Add trusted setting/read route and narrow refund contract behavior; keep current ownership/balance checks.
- [ ] Verify: Run Commerce write/PostgreSQL/idempotency/settings/OpenAPI tests; verify unexpected pending approval is reportable to VerbaOps.
- [ ] Commit: feat: bind refund requests to supervisor approval.

**M6B acceptance/stop:** Legacy tickets default to other; five resources have exact reads; missing currency fails closed; Commerce independently checks refund threshold; Stage 2 idempotency remains intact.

# M6C — Typed proposal tools and policy orchestration

**Branch:** stage6/m6c-proposal-tools
**Deliverable:** Agent creates durable typed proposals and explains server-owned status, without executing a write.

### Task M6C.1 — Durable tool origin and trusted context

**Files**
- Modify: src/verbaops/conversations/persistence.py, src/verbaops/conversations/domain.py, src/verbaops/conversations/repository.py, src/verbaops/conversations/service.py
- Modify: src/verbaops/agent/context.py, src/verbaops/agent/runtime.py, src/verbaops/agent/graph.py, src/verbaops/tools/models.py
- Test: tests/conversations/test_tool_invocation_lifecycle.py, tests/agent/test_tool_loop.py

**Interfaces**
- ConversationService.begin_tool_invocation(scope: ConversationScope, conversation_id: UUID, agent_run_id: UUID, tool_call_id: str, tool_name: str, risk_level: str, arguments: dict[str, Any]) -> ToolInvocationRecord inserts/returns one row keyed by (agent_run_id, tool_call_id). complete_tool_invocation(invocation_id: UUID, status: Literal['succeeded','failed'], result: JSONValue, latency_ms: float, error_code: str | None) finalizes that row.
- ToolExecutionContext contains trusted_context: TrustedContext, conversation_id: UUID, agent_run_id: UUID, tool_invocation_id: UUID. Read-handler customer ID derives from trusted context.
- AgentRuntime.run_turn(trusted_context: TrustedContext, conversation_id: UUID, content: str) threads authenticated context through AgentContext. ToolInvocation retains only proposed/succeeded/failed.

- [ ] RED: Test durable origin reference, failed-handler completion of same row, and rejection of caller identity claims. Run uv run pytest tests/conversations/test_tool_invocation_lifecycle.py tests/agent/test_tool_loop.py -q; expected RED.
- [ ] GREEN: Split trace insert/finalize and pass trusted context/IDs; preserve trace scope and redaction.
- [ ] Verify: Run conversation PostgreSQL race tests and agent/tool tests; each action points to one trace ID.
- [ ] Commit: feat: bind proposal tools to durable invocation context.

### Task M6C.2 — Five proposal tools and policy orchestration

**Files**
- Create: src/verbaops/actions/proposals.py, src/verbaops/tools/proposals.py, tests/tools/test_proposals.py, tests/agent/test_action_proposal_tools.py
- Modify: src/verbaops/tools/models.py, src/verbaops/tools/registry.py, src/verbaops/agent/graph.py, src/verbaops/api/lifespan.py, src/verbaops/api/dependencies.py, src/verbaops/api/routes/conversations.py

**Interfaces**
- ActionProposalService.propose(trusted_context, conversation_id, agent_run_id, tool_invocation_id, proposal) reads scoped Commerce snapshots, resolves currency for refunds, calls pure policy/fingerprint/repository interfaces, and returns ActionRequestSummary.
- Register propose_reschedule_delivery, propose_cancel_order, propose_return, propose_support_ticket, propose_refund with strict inputs and outputs limited to action ID, state, safe summary, reason.
- Existing read tools remain. No Commerce write method is registered in ToolRegistry; proposal tests prove Commerce POST count stays zero.

- [ ] RED: Test all five schemas, absent identity/gate inputs, preflight snapshot, invocation dedup, provider-free output, and zero write POSTs. Run uv run pytest tests/tools/test_proposals.py tests/agent/test_action_proposal_tools.py -q; expected RED.
- [ ] GREEN: Wire lifespan-owned ActionProposalService into the registry; persist proposal-created and initial policy transition.
- [ ] Verify: Run tool/graph/conversation API/Commerce client tests with scripted fake model output; assert denied, awaiting_confirmation, awaiting_approval are server-owned.
- [ ] Commit: feat: add typed action proposal tools.

**M6C acceptance/stop:** Five proposals are durable/deduplicated, identity is server-injected, and no model-visible/executed Commerce write exists.

# M6D — Customer confirmation and safe write execution

**Branch:** stage6/m6d-customer-execution
**Deliverable:** No-supervisor actions execute after trusted customer confirmation and exact read-back.

### Task M6D.1 — Fixed write client and execution claim

**Files**
- Modify: src/verbaops/commerce/client.py, src/verbaops/commerce/models.py, src/verbaops/api/lifespan.py
- Create: src/verbaops/actions/executor.py, tests/actions/test_executor.py, tests/commerce/test_write_client.py

**Interfaces**
- Add typed CommerceClient methods for cancel, reschedule, return, ticket, refund. Fixed route templates, service credential, trusted customer header, Idempotency-Key, typed body; no URL/path argument or registry binding.
- ActionExecutor.execute_ready(action_request_id) refreshes facts, atomically claims ready_to_execute → executing and appends execution_started, commits before network I/O, records bounded outcome afterward.
- Stored UUID key is reused unchanged. Only proven pre-dispatch failures may retry boundedly. ReadTimeout, WriteTimeout, post-dispatch reset, malformed/contradictory 2xx are ambiguous; no read retry policy for writes.

- [ ] RED: Test fixed paths/headers, pre-dispatch same-key retry, definite rejection, post-dispatch timeout reconciliation, and malformed success never becoming succeeded. Run uv run pytest tests/commerce/test_write_client.py tests/actions/test_executor.py -q; expected RED.
- [ ] GREEN: Implement typed POST methods and internal enum dispatch table.
- [ ] Verify: Run CommerceClient contract/executor tests; assert no arbitrary URL, key change, credential exposure, or DB transaction across network I/O.
- [ ] Commit: feat: add internal action executor.

### Task M6D.2 — Exact verification and reconciliation

**Files**
- Create: src/verbaops/actions/verification.py, src/verbaops/actions/reconciliation.py, tests/actions/test_verification.py, tests/actions/test_reconciliation.py, tests/postgres/stage6/test_execution_concurrency.py
- Modify: src/verbaops/actions/executor.py

**Interfaces**
- verify_postcondition(action, write_result, read_back) returns typed match/mismatch for each action. Only exact IDs, scope, requested material values, and expected status permit succeeded.
- ActionReconciler.reconcile(action_request_id: UUID, trusted_context: TrustedContext) -> ActionRequestRecord serializes claim, reads back first, and replays only identical request/key when safe. It cannot create an action/key.
- Missing/unavailable/mismatched read, unexpected pending_manual_approval, or ambiguous dispatch remains unresolved. Definite business rejection is failed.

- [ ] RED: Test exact match and mismatch per action; read-back-first, same-key replay, no-new-key, and unresolved non-success. Run uv run pytest tests/actions/test_verification.py tests/actions/test_reconciliation.py -q; expected RED. Then run test_two_workers_claim_one_action_and_dispatch_once with uv run pytest tests/postgres/stage6/test_execution_concurrency.py -m "postgres and concurrency" -q; expected RED before the locked executor claim.
- [ ] GREEN: Implement five typed verifiers and reconciliation transitions through ActionTransitionService.
- [ ] Verify: Run PostgreSQL action races and assert all missing/malformed reads remain unresolved.
- [ ] Commit: feat: verify and reconcile action outcomes.

### Task M6D.3 — Customer state/confirmation API

**Files**
- Create: src/verbaops/api/routes/action_requests.py, tests/api/test_action_requests.py, tests/actions/test_decisions.py
- Modify: src/verbaops/api/app.py, src/verbaops/api/dependencies.py, src/verbaops/api/lifespan.py

**Interfaces**
- GET /v1/action-requests/{action_request_id} returns a safe ActionRequestView scoped to the owning customer or authorized same-tenant supervisor. Existing GET /v1/conversations/{conversation_id} remains the customer-scoped reload source for active views.
- Actor routes are POST /v1/action-requests/{action_request_id}/confirmation, /rejection, /approval, /approval-rejection, and /reconciliation. The first four accept exactly {proposal_fingerprint}; reconciliation accepts no body, key, or state and is available only to the owning customer or authorized same-tenant supervisor. All endpoints derive actors from TrustedContext; same-decision replay is idempotent; opposite/stale decision conflicts.
- No body accepts actor, state, tenant/customer, role, policy result, or idempotency key. Cross-scope IDs use sanitized non-enumerating 404.
- Refresh material Commerce facts before accepting confirmation; if relevant state or displayed values changed, expire the old request and require a new fingerprint. A customer may withdraw while awaiting approval or confirmation; withdrawal serializes with supervisor decisions. A no-approval confirmation triggers the internal executor after the state/event transaction commits. Awaiting-approval requests cannot be confirmed early. No public execute/state-setting endpoint.

- [ ] RED: Test confirm/reject, exact fingerprint, stale/expired, same retry, opposite conflict, no execute route, and test_cross_customer_action_id_matches_random_id_not_found. Add test_stale_fingerprint_cannot_replay_confirmation_or_approval here for confirmation; M6E.1 extends it for approval. Run uv run pytest tests/api/test_action_requests.py -q; expected RED.
- [ ] GREEN: Add actor routes/service dependencies; invoke executor only when the server determines the final gate has passed.
- [ ] Verify: Run API/action/executor/auth regressions; assert identity is never accepted from browser/model.
- [ ] Commit: feat: add customer action confirmation API.

**M6D acceptance/stop:** No-approval actions execute only after customer confirmation; gated cancellation/refund remain awaiting_approval; success has exact read-back; ambiguous writes reuse the original key or remain unresolved.

# M6E — Human approval and high-risk actions

**Branch:** stage6/m6e-supervisor-hitl
**Deliverable:** Only unusual eligible cancellations and refunds above 500.00 require a separate trusted supervisor, before customer confirmation.

### Task M6E.1 — Supervisor decisions and cancellation gate

**Files**
- Modify: src/verbaops/api/routes/action_requests.py, src/verbaops/actions/policy.py, src/verbaops/actions/proposals.py
- Create: tests/actions/test_approval.py
- Modify: tests/api/test_action_requests.py, tests/actions/test_decisions.py

**Interfaces**
- POST /approval and /approval-rejection accept proposal_fingerprint only. Enforce support_supervisor, proposer_id != supervisor principal, tenant scope, freshness, and locked state.
- Approval records actor/time/fingerprint and changes awaiting_approval → awaiting_confirmation. Customer confirmation follows. Rejection is terminal; same decision replay is idempotent. Customer withdrawal while awaiting approval races through the same locked transition service; the first valid decision wins.
- Only otherwise-eligible PROCESSING orders and/or LABEL_CREATED shipments require approval. Reschedule including IN_TRANSIT, other eligible cancellations, eligible returns, and ordinary tickets do not.

- [ ] RED: Test role and tenant-admin denial, test_proposer_cannot_approve_own_action, approval-before-confirmation, stale/replayed approval in test_stale_fingerprint_cannot_replay_confirmation_or_approval, rejection, and cancellation matrix. Run uv run pytest tests/actions/test_approval.py tests/api/test_action_requests.py -q; expected RED.
- [ ] GREEN: Implement locked approval/rejection through ActionTransitionService and action-specific policy.
- [ ] Verify: Run policy, API, and PostgreSQL gate-race tests; approval never overrides Commerce eligibility.
- [ ] Commit: feat: add unusual cancellation approval flow.

### Task M6E.2 — Bound high-value refund approval

**Files**
- Modify: src/verbaops/actions/executor.py, src/verbaops/actions/proposals.py, src/verbaops/actions/verification.py
- Modify: tests/actions/test_approval.py, tests/actions/test_executor.py, tests/integration/test_stage6_refunds.py

**Interfaces**
- Resolve NovaCommerce currency before confirmation; VerbaOps uses strict amount > 500.00. Exactly 500.00 is not gated.
- Supervisor approves immutable action/fingerprint; customer confirms the same fingerprint afterward. Executor builds RefundApprovalReference only from stored approval and sends it on authenticated Commerce write.
- NovaCommerce independently checks threshold/eligibility and stores reference in Commerce event. requires_manual_approval may remain true with status approved; no payment is issued.
- Unexpected pending_manual_approval becomes unresolved.

- [ ] RED: Test 499.99/500.00/500.01; missing currency before confirmation; missing/wrong-action/stale evidence; valid evidence; remaining-refundable denial; replay; unexpected pending. Run uv run pytest tests/actions/test_approval.py tests/actions/test_executor.py tests/integration/test_stage6_refunds.py -q; expected RED.
- [ ] GREEN: Construct reference from the stored approval; verify exact approved refund without implying settlement.
- [ ] Verify: Run NovaCommerce refund/PostgreSQL and VerbaOps refund/API/executor tests; >500 without reference causes no mutation.
- [ ] Commit: feat: bind high value refunds to approval.

**M6E acceptance/stop:** Initial supervisor flows are exactly unusual eligible cancellation and >500.00 refund. Proposer and approver differ; approval precedes confirmation; reschedule never awaits approval.

# M6F — Agent and browser workflow integration

**Branch:** stage6/m6f-agent-web-workflow
**Deliverable:** Agent reports only server-owned state; browser shows exact proposal and actor controls through existing server-only BFF.

### Task M6F.1 — Structured status and durable conversation views

**Files**
- Modify: src/verbaops/agent/state.py, src/verbaops/agent/runtime.py, src/verbaops/agent/graph.py, src/verbaops/api/routes/conversations.py, src/verbaops/conversations/domain.py, src/verbaops/actions/repository.py
- Create: tests/agent/test_action_status.py, tests/api/test_conversation_actions.py

**Interfaces**
- Tool results and AgentTurnResult carry ActionRequestSummary from ActionProposalService, not model-authored lifecycle claims.
- Existing GET /v1/conversations/{conversation_id} adds owner-scoped active ActionRequestView loaded from action_requests. This is the durable reload source; model memory and ToolInvocation result_json are not authoritative.
- Status explains only current state and permitted next actor operation; safe values remain bound to stored payload/fingerprint.

- [ ] RED: Test scripted model status, safe summaries, durable reload, and no success without verification. Run uv run pytest tests/agent/test_action_status.py tests/api/test_conversation_actions.py -q; expected RED.
- [ ] GREEN: Project summaries into turn responses and load active views via the scoped conversation read.
- [ ] Verify: Run agent/conversation/grounding regressions using fake output; Stage 5 evidence never grants policy.
- [ ] Commit: feat: expose durable action state to conversations.

### Task M6F.2 — Action BFF routes

**Files**
- Create: apps/web/src/app/api/action-requests/[actionRequestId]/route.ts, apps/web/src/app/api/action-requests/[actionRequestId]/confirmation/route.ts, apps/web/src/app/api/action-requests/[actionRequestId]/rejection/route.ts, apps/web/src/app/api/action-requests/[actionRequestId]/approval/route.ts, apps/web/src/app/api/action-requests/[actionRequestId]/approval-rejection/route.ts, apps/web/src/app/api/action-requests/[actionRequestId]/reconciliation/route.ts, apps/web/src/app/api/action-requests/routes.test.ts
- Modify: apps/web/src/lib/server/request-validation.ts, apps/web/src/lib/server/verbaops.ts

**Interfaces**
- GET route validates UUID path; each POST validates an exact fingerprint-only body (reconciliation has no caller-supplied key/state). Routes forward only fixed VerbaOps paths through forwardToVerbaOps with no-store.
- BFF accepts no identity, lifecycle, currency, or idempotency fields; bearer and Commerce credentials stay server-side.

- [ ] RED: Test malformed IDs/bodies, extra identity fields, fixed route/fingerprint forwarding, backend errors, and secret redaction. Run corepack pnpm --dir apps/web test; expected RED.
- [ ] GREEN: Add only the scoped GET and five actor-intent/reconciliation BFF routes.
- [ ] Verify: Run corepack pnpm --dir apps/web lint, typecheck, and test; inspect outbound payloads for identity/secrets.
- [ ] Commit: feat: add action request BFF routes.

### Task M6F.3 — Customer and supervisor action views

**Files**
- Create: apps/web/src/components/action-request-card.tsx, apps/web/src/components/action-request-card.test.tsx, apps/web/src/app/action-requests/[actionRequestId]/page.tsx
- Modify: apps/web/src/components/chat.tsx, apps/web/src/app/api/conversations/[conversationId]/route.ts
- Test: apps/web/tests/smoke/stage6-actions.spec.ts

**Interfaces**
- Customer card shows exact action, target, material values, consequences, current state, confirm/reject controls. Supervisor direct review shows the stored proposal and approve/reject controls; no assignment queue or general support console.
- On reload, Chat restores only the current conversation ID from sessionStorage and calls existing scoped GET conversation to reload messages and active ActionRequestView. VerbaOps remains the source of state/authorization.
- Use existing server-only BFF and trusted auth mapping. No role selector, browser-held credential, production session/IdP, or voice stack.

- [ ] RED: Test all five confirmation summaries, customer/supervisor pending states, failed/unresolved result copy, and that success appears only for a verified state. Run corepack pnpm --dir apps/web test; expected RED.
- [ ] GREEN: Add ActionRequestCard, direct review page, and conversation reload from server-owned active views.
- [ ] Verify: Run corepack pnpm --dir apps/web lint, typecheck, test, build, and smoke; browser submits only request ID/fingerprint.
- [ ] Commit: feat: add confirmed action views.

**M6F acceptance/stop:** Customer/supervisor views show exact stored values and current state; BFF stays server-only; no production identity or voice system is added.

# M6G — Stage 6 acceptance, security regression, and lock

**Branch:** stage6/m6g-acceptance-lock
**Deliverable:** Permanent provider-free evidence covers all five actions, dangerous failures, both stores, and browser workflow.

### Task M6G.1 — Black-box action acceptance

**Files**
- Create: scripts/run_stage6_acceptance.py, tests/acceptance/stage6/__init__.py, tests/acceptance/stage6/conftest.py, tests/acceptance/stage6/test_action_workflows.py, tests/acceptance/stage6/test_action_security.py, tests/acceptance/stage6/test_refund_boundaries.py
- Modify: tests/acceptance/agent/conftest.py, tests/support/fake_llm.py, tests/test_commerce_acceptance_runner.py

**Interfaces**
- Runner uses deterministic auth, test databases, scripted model output, and existing Commerce test infrastructure; no paid/live provider call.
- Cover all five actions, confirmation summaries, unusual cancellation/>500 approval, no supervisor reschedule even IN_TRANSIT, stale fingerprint, scope isolation, idempotency, exact verification, unresolved, audit, and absence of model execute tool.
- Browser smoke covers customer decisions and direct supervisor review; APIs remain authorization/state authority.

- [ ] RED: Add black-box flows and all five Review Focus cases. Run uv run pytest tests/acceptance/stage6 -q; expected RED against absent routes/behavior.
- [ ] GREEN: Add provider-free runner/fixtures using scripted fake output.
- [ ] Verify: Run uv run python scripts/run_stage6_acceptance.py, focused API/action tests, Commerce acceptance, and Playwright smoke; assert no external inference call.
- [ ] Commit: test: add Stage 6 black box acceptance.

### Task M6G.2 — Permanent CI and closeout

**Files**
- Modify: Makefile, .github/workflows/ci.yml
- Create: tests/test_stage6_ci_contract.py

**Interfaces**
- stage6-action-contract runs uv run pytest tests/actions tests/api/test_action_requests.py tests/tools/test_proposals.py tests/agent/test_action_proposal_tools.py tests/novacommerce/test_stage6_ticket_category.py tests/novacommerce/test_stage6_exact_reads.py tests/novacommerce/test_stage6_refunds.py -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance" -q.
- stage6-postgres-contract applies uv run alembic upgrade head and uv run alembic -c alembic-commerce.ini upgrade head, then runs uv run pytest tests/postgres/stage6 tests/integration/test_stage6_refunds.py -m "postgres and contract" -q and uv run pytest tests/postgres/stage6 -m "postgres and concurrency" -q. Its CI job creates separate verbaops_test and novacommerce_test databases on one PostgreSQL service and sets both VERBAOPS_DATABASE__URL and NOVACOMMERCE_TEST_DATABASE_URL.
- stage6-acceptance runs uv run python scripts/run_stage6_acceptance.py.
- Extend quality with deterministic action tests; add one Stage 6 PostgreSQL job; extend existing acceptance/web jobs rather than one job per feature. Use existing postgres, contract, concurrency, critical_race markers. Exact-head hosted CI must be green.
- Keep current Ruff, format, mypy, pytest, pre-commit, OpenAPI, migration, Docker, Commerce/agent acceptance, and web quality/smoke gates.

- [ ] RED: Test target selection, both migration heads, and no historical migration edits. Run uv run pytest tests/test_stage6_ci_contract.py -q; expected RED before target/workflow changes.
- [ ] GREEN: Add targets/workflow wiring and two-database setup without tiny-job proliferation.
- [ ] Verify: Run make stage6-action-contract, make stage6-postgres-contract, make stage6-acceptance, make check, make web-check, make web-smoke, docker build --target runtime -t verbaops:stage6 ., and git diff --check. Obtain green hosted CI for exact implementation head.
- [ ] Commit: test: lock Stage 6 safety acceptance.

**M6G acceptance/stop:** Every Stage 6 completion criterion has a deterministic test/contract; exact-head CI is green; closeout evidence makes no Stage 5 retrieval promotion.

## Per-milestone branch strategy

Create only after plan approval and the prior milestone's merge to main:

| Milestone | Branch |
|---|---|
| M6A | stage6/m6a-action-lifecycle |
| M6B | stage6/m6b-commerce-contracts |
| M6C | stage6/m6c-proposal-tools |
| M6D | stage6/m6d-customer-execution |
| M6E | stage6/m6e-supervisor-hitl |
| M6F | stage6/m6f-agent-web-workflow |
| M6G | stage6/m6g-acceptance-lock |

No implementation branch is created by this planning change.

## Spec coverage and self-review

| Approved spec sections | Owning plan milestones |
|---|---|
| 1–4 scope, repository, invariants, boundaries | Global Constraints; audit; M6A–M6G |
| 5 gates; 6 proposal contract | M6A.1–2; M6C.2; M6E |
| 7 persistence; 8 state machine; 9 policy | M6A.1–4 |
| 10 customer confirmation; 11 HITL/refund approval | M6D.3; M6E.1–2 |
| 12 execution; 13 idempotency/retries; 14 verification | M6D.1–2; M6G.1 |
| 15 API; 16 agent/web/voice; 17 concurrency | M6D.3; M6F; M6A.4; M6G.1 |
| 18 failures; 19 security/privacy | M6D; M6E; M6G.1 |
| 20 contract gaps; 21 testing | M6B; M6G |
| 22 alternatives; 23 non-goals | Global Constraints |
| 24 completion criteria; 25 self-review | M6G; this coverage/self-review |

Self-review findings and resolutions:

- Corrected the customer conversation reload method to GET and froze the actor API route shapes to the approved spec.
- Added a separate PostgreSQL concurrency command so the dangerous duplicate-execution test cannot be accidentally deselected by the unit-test marker filter.
- Strengthened the migration plan with DB-level rejection of event UPDATE/DELETE, and made supervisor proposal scope, material-snapshot freshness, withdrawal races, and Commerce contract CI coverage explicit.
- Preserved the approved gate matrix: reschedule always requires customer confirmation and never supervisor approval, including Commerce-eligible IN_TRANSIT; only unusual eligible cancellations and refunds above 500.00 use supervisor approval.
- action_events remains append-only but not event-sourced; current state is authoritative.
- Currency ownership is one NovaCommerce Settings source plus authenticated narrow read; absence fails closed before confirmation.
- ToolInvocation is created before proposal execution so actions reference a durable origin ID.
- Write retries remain separate from read retries; ambiguity is read-back-first and same-key only.
- Seven milestones are dependency ordered and independently reviewable. No architecture contradiction or placeholder remains.
