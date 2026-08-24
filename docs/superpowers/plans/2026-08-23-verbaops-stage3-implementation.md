# VerbaOps AI Stage 3 Master Implementation Plan

**Source of truth:** `docs/superpowers/specs/2026-08-23-verbaops-stage3-ai-provider-text-agent-design.md`

**Execution mode:** execution is single-agent unless the user explicitly
changes this instruction. Detailed TDD task plans for M3B–M3F must be refined at the
start of each milestone from the then-current merged repository; this document
does not invent their future implementation details.

**Current scope:** this branch implements M3B only; M3A is merged on the base.

## Locked global constraints

- Required base is exactly `6c60a557d808d7db777b3a7854573011351f28d5`.
- LiteLLM is a separate Docker service and the provider boundary is HTTP-only.
- No LiteLLM Python SDK or vendor LLM SDK imports in VerbaOps.
- Capability aliases are exactly `agent-fast`, `agent-reasoning`, `eval-judge`,
  and `embedding-multilingual`; only `agent-fast` is exercised in M3A.
- `ResponseMetadata` keeps gateway request ID, gateway model ID, model, and
  cost as distinct nullable fields; unavailable values are never inferred.
- `LiteLLMClient` consumes an injected reusable `httpx.AsyncClient`; the caller
  owns its lifecycle.
- `VERBAOPS_LLM` is immutable and contains `base_url`, `api_key: SecretStr`,
  and positive `timeout_seconds`.
- No external provider or paid credential is required at test runtime.
- No NovaCommerce production, migration, canonical seed, or Stage 2 OpenAPI
  changes.
- Stage 3 explicitly excludes write tools and mutation operations,
  cancellation/reschedule/return/ticket mutations, RAG, embeddings/vector
  search, Arabic specialization, voice, multi-agent architecture, HITL/
  approval, and streaming UI.
- Every milestone production behavior change follows RED, expected failure, minimal
  GREEN, regression verification, and a focused commit.

## Milestone roadmap and exit criteria

| Milestone | Scope | Exit criterion |
|---|---|---|
| M3A | LLM Gateway & Provider Layer | Real LiteLLM proxy contract, typed plain/structured generation, safe tool/metadata/error normalization, reusable client ownership, secret redaction, and all Stage 1/2 gates green. |
| M3B | Conversation & Trace Persistence | Approved conversation/turn/message/trace persistence and lifecycle are implemented and tested from the then-current merged repository. |
| M3C | NovaCommerce Read Client & Typed Tool Registry | Typed NovaCommerce read client and allowlisted read-only tool registry are validated against the locked API with no mutation surface. |
| M3D | First LangGraph Read-Only Agent Runtime | One bounded text-only read-only agent turn works through M3A and M3C with deterministic, allowlisted tools and no writes, multi-agent, or HITL behavior. |
| M3E | Conversation API & End-to-End Agent Acceptance | The persisted read-only agent flow is exposed and accepted end to end with safe failure behavior and no mutation surface. |
| M3F | Minimal Next.js Web Chat & Stage 3 Lock | Minimal text chat completes the approved read-only flow and all security/regression gates pass for the Stage 3 lock. |

## M3A completed prerequisite

### 1. Establish the correction tests

- Add failing tests for the exact metadata field names and header/body
  separation.
- Add a failing test proving two sequential calls use one injected
  `httpx.AsyncClient` and that the client does not close it.
- Add failing tests for invalid JSON and Pydantic validation failures from
  `generate_structured()`.
- Update the real-proxy contract assertions to require separate gateway model
  ID and model values.

### 2. Implement the minimal correction

- Rename ambiguous metadata fields to the frozen contract.
- Inject the reusable client into `LiteLLMClient`; remove per-call client
  creation and closing.
- Add `LLMStructuredOutputError` and use it only for structured content parse or
  validation failures.
- Keep malformed gateway envelopes, protocol data, and tool-call structures as
  `LLMProtocolError`.

### 3. Verify the M3A boundary

The M3A gateway and real proxy contract were merged before this M3B branch.

### 4. Review and handoff

The M3A correction was reviewed and merged before M3B began.

## M3B TDD task plan

### 1. Establish the persistence RED suite

- Add real PostgreSQL tests for the five-table schema, constraints, indexes,
  trusted scope isolation, foreign/nonexistent equivalence, and JSONB traces.
- Add lifecycle tests for committed turn start, independent trace commits,
  completion/failure, rollback atomicity, busy turns, and stale-run recovery.
- Keep the M3B marker and PostgreSQL environment isolated from the vanilla
  NovaCommerce PostgreSQL jobs.

### 2. Implement the minimal persistence boundary

- Add migration `0002_agent_runtime_v1` without changing Commerce migrations.
- Add separate SQLAlchemy persistence models, domain records, repository, and
  short-transaction lifecycle service under `src/verbaops/conversations/`.
- Require tenant/principal scope on every repository/service conversation read.
- Enforce one running run per conversation with a PostgreSQL partial unique
  index and atomically recover stale runs before starting a new turn.

### 3. Verify the M3B boundary

Run the focused PostgreSQL suite and migration upgrade/downgrade checks, then
all normal, Commerce, M3A gateway, Docker, and existing PostgreSQL gates.
Confirm no LangGraph, Commerce client/tools, HTTP conversation API, frontend,
RAG, writes, voice, Arabic specialization, HITL, or multi-agent behavior was
introduced.

### 4. Review and handoff

Request review, push `stage3/m3b-agent-persistence`, create a draft PR, wait
for hosted CI, and report the evidence. Do not merge and do not begin M3C.

## Future milestone planning rule

At the start of M3B, M3C, M3D, M3E, and M3F, create a fresh detailed TDD task
plan after inspecting the then-current merged repository. Preserve the exact
milestone names, scopes, non-goals, and exit criteria above; do not pre-commit
future code structure or dependencies in this master plan.
