# VerbaOps Stage 7 — Browser Realtime Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task with ONE primary agent. Do not use sub-agents unless the human explicitly authorizes them. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Stage 7 browser realtime voice channel as a customer-only, provider-backed, browser-to-Voice-Worker path that reuses the Stage 6 AgentRuntime and action lifecycle without widening authorization or changing the Stage 6 supervisor workflow.

**Architecture:** The browser creates a durable, server-owned voice session through VerbaOps. VerbaOps mints a narrowly scoped LiveKit participant token. A separately authenticated Voice Worker consumes LiveKit audio, converts only final STT events into bounded internal transcript submissions, reconstructs a CUSTOMER-only `TrustedContext` from the durable session, invokes the existing `AgentRuntime`, and returns final assistant/action state for TTS and browser rendering. Durable state, PostgreSQL uniqueness, Stage 6 transitions, and browser/server authentication remain authoritative; provider adapters and fake adapters are replaceable boundaries.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, SQLAlchemy asyncio, Alembic, PostgreSQL, existing VerbaOps AgentRuntime/LangGraph/action lifecycle, Next.js 16, React 19, TypeScript, Vitest, Playwright, LiveKit WebRTC/Agents, ElevenLabs Scribe v2 Realtime STT, ElevenLabs low-latency TTS/Flash v2.5 where supported, and the existing provider-free CI/test harness. Verify current official provider documentation and select compatible package ranges during implementation; do not invent versions in advance.

**Spec:** `docs/superpowers/specs/2026-10-07-verbaops-stage7-realtime-voice-design.md` at approved head `5217e5dfbf34433edaa152fe121fff8b2ab4299e`.

## Global Constraints

- This plan is the implementation roadmap; writing this file does not implement Stage 7.
- Execute with one primary Codex agent only. Do not use sub-agents.
- Work milestone-by-milestone in dependency order: M7A → M7B → M7C → M7D → M7E → M7F → M7G.
- Preserve the approved Stage 6 baseline at `8926d54bbef4422fcf3bb861a36de1ad6dcd5200` and all approved Stage 7 decisions in the spec.
- Stage 7 browser voice is a customer-only channel.
- Browser bootstrap requires trusted `has_customer_authority(trusted_context)`.
- Internal worker execution reconstructs exactly the conceptual context below from the durable voice session:

  ```python
  TrustedContext(
      tenant_id=voice_session.tenant_id,
      principal_id=voice_session.principal_id,
      customer_id=voice_session.customer_id,
      roles=frozenset({Role.CUSTOMER}),
  )
  ```

- `principal_id` remains the original trusted principal for audit and proposer identity. It is not an authorization role.
- The original caller role set is never persisted on `voice_sessions` and is never copied into voice execution.
- CUSTOMER + SUPPORT_AGENT, CUSTOMER + SUPPORT_SUPERVISOR, and CUSTOMER + TENANT_ADMIN all execute through voice as CUSTOMER only.
- Support-only, supervisor-only, and tenant-admin-only callers cannot bootstrap customer voice.
- Voice Worker requests accept no role field, principal field, tenant field, customer field, room field, or arbitrary authorization claims.
- LiveKit metadata, STT output, LLM output, browser state, and provider payloads cannot supply or widen roles.
- Ended, expired, invalid, or wrong-scope sessions cannot reconstruct an active voice customer context.
- Do not invent production IdP revocation infrastructure. Reconcile checks with the approved bounded token/session expiry and lifecycle semantics.
- Do not persist raw audio, provider secrets, access tokens, arbitrary provider JSON, or role snapshots.
- Use the existing Stage 6 lifecycle and decision rules. Do not create a public direct action-execution path.
- Keep supervisor approval in the separately authenticated browser supervisor workflow. Voice may describe that approval is required but cannot perform it.
- Keep `voice_turn_id` idempotency durable and deterministic. Do not rely on an in-memory deduplication cache.
- Keep the final transcript as the durable user message. Partial STT events remain memory-only and do not invoke AgentRuntime.
- Arm spoken confirmation only after the complete confirmation summary has played. An interruption before completion must not leave an armed confirmation gate.
- English is the Stage 7 quality language. MSA, Egyptian Arabic, and code-switch plumbing may be bounded, but Stage 8 owns multilingual quality.
- Preserve the Stage 5 status: `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE`.
- Preserve raw-audio non-persistence, LiveKit architecture, cascaded STT → AgentRuntime → TTS, ElevenLabs reference providers, migration number `0007_voice_sessions_v1`, final transcript semantics, Stage 6 lifecycle, Stage 8 boundary, and M7A–M7G decomposition.
- Do not modify unrelated source, tests, migrations, dependencies, Docker, Makefile, CI, README, product requirements, or other files while authoring this roadmap. Those changes belong only to future milestone execution.
- Every implementation task must add provider-free tests before or with the behavior, and every milestone must leave the existing Stage 6/web/CI checks intact.
- Do not add a fallback provider, speech-to-speech primary path, Vapi/Retell integration, custom transport, Redis confirmation authority, or undocumented UI redesign.

## Review Focus

These cases are release-blocking and must remain visible throughout execution:

1. Duplicate final transcript submission, including simultaneous PostgreSQL requests, must produce one user message, one AgentRun, one assistant outcome, and no duplicate action proposal. Primary tests: `tests/postgres/voice/test_final_turn_idempotency.py::test_duplicate_final_after_commit_returns_existing_result` and `tests/postgres/voice/test_final_turn_idempotency.py::test_simultaneous_same_voice_turn_id_has_one_winner` (M7B/M7E/G).
2. An interrupted confirmation summary must not arm confirmation. A later `confirm` must perform zero Stage 6 decisions until the full summary is replayed and completed. Primary test: `tests/voice/test_playout_gate.py::test_interrupted_summary_then_confirm_never_decides` (M7D/E/G).
3. Composed caller roles must narrow to CUSTOMER. A caller with CUSTOMER + SUPPORT_AGENT, CUSTOMER + SUPPORT_SUPERVISOR, or CUSTOMER + TENANT_ADMIN may bootstrap, but the worker’s reconstructed context must contain exactly `Role.CUSTOMER`. Primary tests: `tests/api/test_voice_sessions.py::test_composed_roles_are_customer_only` and `tests/api/test_voice_transcripts.py::test_worker_cannot_inherit_composed_roles` (M7A/B/G).
4. Concurrent voice/text turns for one conversation must obey the existing one-running-turn rule without duplicate action creation or an in-memory queue. Primary test: `tests/postgres/voice/test_voice_text_concurrency.py::test_voice_and_text_turns_have_one_winner` (M7E/G).
5. A worker restart after action creation but before complete spoken summary must replay authoritative durable state without executing twice or leaving an unsafe confirmation gate. A worker restart after an armed ephemeral gate must also destroy that gate and require complete summary replay before a new confirmation. Primary tests: `tests/voice/test_worker_recovery.py::test_restart_after_action_before_summary_replays_without_duplicate_execution` and `tests/voice/test_worker_recovery.py::test_restart_after_armed_confirmation_requires_summary_replay` (M7E/G).

## Repository Ownership Map

| Concern | Current seam | Planned ownership | Primary milestone |
|---|---|---|---|
| Trusted identity and roles | `src/verbaops/auth/context.py`, `src/verbaops/auth/provider.py` | Reuse `TrustedContext`; add a dedicated worker credential/context primitive without changing role semantics | M7A |
| Settings and secrets | `src/verbaops/config/settings.py` | Add typed voice settings and secret handling; keep secrets out of repr/logging | M7A |
| Durable voice lifecycle | `src/verbaops/voice/`, Alembic migration `0007_voice_sessions_v1` | New voice domain/repository/service and session lifecycle | M7A |
| Conversation provenance | `src/verbaops/conversations/persistence.py`, `domain.py`, `repository.py`, `service.py` | Add interaction mode/session/turn provenance and preserve text compatibility | M7A/B |
| Agent runtime | `src/verbaops/agent/runtime.py`, `context.py`, `state.py` | Add explicit voice provenance and return existing Stage 6 summaries | M7B |
| Internal transcript boundary | `src/verbaops/api/dependencies.py`, `routes/`, `app.py` | Strict worker-authenticated final transcript endpoint | M7B |
| STT and TTS seams | new `src/verbaops/voice/speech.py`, `worker.py`, provider adapters | Normalize provider events and isolate LiveKit/ElevenLabs from application policy | M7B/F |
| Stage 6 action semantics | `src/verbaops/actions/*` | Read existing action projections; use existing decision service; no duplicate executor | M7D/E |
| Browser BFF | `apps/web/src/lib/server/verbaops.ts`, `apps/web/src/app/api/` | Add fixed voice bootstrap/end routes with server-only token handling | M7C |
| Browser UI | `apps/web/src/components/chat.tsx`, `action-request-card.tsx` | Add focused `VoicePanel` and continuity state without replacing Chat | M7C |
| Browser test harness | `apps/web/vitest.config.ts`, `playwright.config.ts`, existing route tests | Mock transport/provider boundaries; no microphone or live provider in CI | M7C/G |
| CI and commands | `Makefile`, `.github/workflows/ci.yml` | Add focused contract/acceptance targets while retaining existing checks | M7G |
| Provider validation evidence | new `docs/evaluation/stage7-realtime-voice-validation.md` | Store bounded, non-secret validation report; never store raw audio or credentials | M7F |

## Frozen Interfaces and Contracts

The following interfaces are frozen for implementation across milestones. If execution discovers a material reason to change a cross-milestone DTO, enum, method signature, or route shape, STOP and obtain human design/roadmap approval before changing the contract. Minor local/private helper names do not require approval.

### Voice session domain

Own in `src/verbaops/voice/domain.py` and `src/verbaops/voice/models.py`:

```python
class VoiceSessionState(StrEnum):
    CREATED = "created"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ENDED = "ended"


@dataclass(frozen=True)
class VoiceSessionRecord:
    id: UUID
    tenant_id: UUID
    principal_id: UUID
    customer_id: UUID
    conversation_id: UUID
    transport_provider: str
    stt_provider: str
    tts_provider: str
    room_identity: str
    participant_identity: str
    status: VoiceSessionState
    created_at: datetime
    connected_at: datetime | None
    ended_at: datetime | None
    error_code: str | None


class VoiceSessionBootstrap(BaseModel):
    voice_session_id: UUID
    conversation_id: UUID
    livekit_url: AnyHttpUrl
    room_token: str
    token_expires_at: datetime
    status: VoiceSessionState
```

At successful bootstrap, `status` is `VoiceSessionState.CREATED`. `VoiceSessionRecord` intentionally has no `roles`, `claims`, transport token, `raw_audio`, `provider_payload`, or secret fields. `VoiceSessionBootstrap` is the exact bounded customer-facing response; the room token is never logged, persisted, placed in browser storage, or accepted back as an authorization claim. Room identity and participant identity remain server-owned/session-owned values and are not exposed in this browser response.

### Session service and transport token issuer

Own in `src/verbaops/voice/service.py` and `src/verbaops/voice/transport.py`:

```python
class VoiceSessionService:
    async def create_customer_session(
        self,
        trusted_context: TrustedContext,
        conversation_id: UUID | None,
    ) -> VoiceSessionBootstrap: ...

    async def get_customer_session(
        self,
        session_id: UUID,
        trusted_context: TrustedContext,
    ) -> VoiceSessionRecord: ...

    async def get_worker_session(
        self,
        session_id: UUID,
        worker_context: VoiceWorkerContext,
    ) -> VoiceSessionRecord: ...

    async def mark_connecting(self, session_id: UUID) -> VoiceSessionRecord: ...
    async def mark_connected(self, session_id: UUID) -> VoiceSessionRecord: ...

    async def end_customer_session(
        self,
        session_id: UUID,
        trusted_context: TrustedContext,
    ) -> VoiceSessionRecord: ...


class LiveKitTokenIssuer(Protocol):
    async def mint_customer_token(
        self,
        *,
        room_identity: str,
        participant_identity: str,
        ttl: timedelta,
    ) -> str: ...
```

The service owns tenant/principal/customer/session lifecycle checks. The issuer owns only server-generated room/participant identity, minimum grants, and bounded expiry. No endpoint accepts caller-supplied room, participant, grant, role, or token values.

### Worker authentication and strict transcript request

Own in `src/verbaops/voice/auth.py` and `src/verbaops/voice/models.py`:

```python
@dataclass(frozen=True)
class VoiceWorkerContext:
    service_name: Literal["voice_worker"]


def authenticate_worker(credential: OpaqueCredential) -> VoiceWorkerContext: ...


class VoiceFinalTranscriptRequest(BaseModel):
    voice_turn_id: UUID
    transcript: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
```

The internal request body is exactly `{"voice_turn_id": ..., "transcript": ...}`. Worker authentication is a dependency, not a body field. The worker cannot submit identity, roles, tenant, customer, conversation, room, or arbitrary metadata.

### AgentRuntime provenance

Own in `src/verbaops/agent/context.py` and `src/verbaops/agent/runtime.py`:

```python
class InteractionMode(StrEnum):
    TEXT = "text"
    VOICE = "voice"


async def run_turn(
    self,
    trusted_context: TrustedContext,
    conversation_id: UUID,
    content: str,
    *,
    interaction_mode: InteractionMode = InteractionMode.TEXT,
    voice_session_id: UUID | None = None,
    voice_turn_id: UUID | None = None,
) -> AgentTurnResult: ...
```

Text calls retain current behavior and reject voice-only IDs. Voice calls require both voice IDs, validate them against the durable session, and persist provenance on `AgentRun`. `interaction_mode` is provenance/presentation metadata and never changes authorization.

### Speech events and worker adapter boundaries

Own in `src/verbaops/voice/speech.py` and `src/verbaops/voice/worker.py`:

```python
class SpeechEventKind(StrEnum):
    PARTIAL = "partial"
    FINAL = "final"


@dataclass(frozen=True)
class SpeechEvent:
    kind: SpeechEventKind
    transcript: str
    voice_turn_id: UUID | None


class STTAdapter(Protocol):
    async def events(self) -> AsyncIterator[SpeechEvent]: ...


class PlayoutHandle(Protocol):
    @property
    def first_audio_at(self) -> datetime | None: ...

    async def wait_complete(self) -> None: ...
    async def cancel(self) -> None: ...


class TTSAdapter(Protocol):
    async def speak(self, text: str) -> PlayoutHandle: ...


class VoiceWorkerCoordinator:
    async def handle_speech_event(self, event: SpeechEvent) -> None: ...
    async def handle_playout_completed(self) -> None: ...
    async def handle_interruption(self) -> None: ...
```

PARTIAL events update ephemeral UI/worker state only. FINAL events are the only events that call the internal transcript boundary. The coordinator must be injectable with fake transport/STT/TTS implementations for all provider-free tests.

### Voice action presentation and confirmation

Own in `src/verbaops/voice/actions.py` and `src/verbaops/voice/confirmation.py`:

```python
class VoiceTurnOutcome(StrEnum):
    NORMAL_ANSWER = "normal_answer"
    ACTION_PENDING = "action_pending"
    AWAITING_APPROVAL = "awaiting_approval"
    ACTION_RESULT = "action_result"
    FAILURE = "failure"


class VoiceActionPrompt(BaseModel):
    action_request_id: UUID
    action_type: ActionType
    state: ActionState
    proposal_fingerprint: str
    spoken_summary: str
    required_next_actor: str
    permitted_operations: tuple[Literal["confirm", "reject"], ...]


class VoiceTurnResult(BaseModel):
    voice_session_id: UUID
    conversation_id: UUID
    voice_turn_id: UUID
    agent_run_id: UUID
    assistant_message_id: UUID
    assistant_text: str
    outcome: VoiceTurnOutcome
    action_requests: tuple[ActionRequestSummary, ...]
    action_prompt: VoiceActionPrompt | None


@dataclass(frozen=True)
class PendingVoiceConfirmation:
    voice_session_id: UUID
    action_request_id: UUID
    proposal_fingerprint: str
    summary_text: str
    tts_playout_id: str
    armed: bool


def parse_confirmation(text: str) -> ConfirmationIntent: ...
```

`VoiceActionPrompt` is derived from the stored Stage 6 projection and proposal fingerprint. It is not an instruction to execute. A pending gate is session-bound, action-bound, and fingerprint-bound, and is authoritative only after full playout completion.

## Milestone Dependency and Branch Contract

| Milestone | Branch | Depends on | Outcome gate |
|---|---|---|---|
| M7A | `stage7/m7a-voice-foundation` | Stage 6 baseline | Durable sessions, settings, token issuance, bootstrap/end, and worker auth are tested and scoped |
| M7B | `stage7/m7b-voice-worker` | M7A | Final transcript path, runtime provenance, idempotency, speech events, and worker coordinator exist behind fakes |
| M7C | `stage7/m7c-browser-voice` | M7A, M7B contracts | Browser can start/end and render mocked voice state without credentials or hardware |
| M7D | `stage7/m7d-voice-actions` | M7B, M7C state path | Voice action summaries, confirmation grammar, playout gate, and Stage 6 bridge are deterministic |
| M7E | `stage7/m7e-turn-safety` | M7D | Races, interruption, reconnect, restart, and failure state machines are safe under provider-free tests |
| M7F | `stage7/m7f-provider-validation` | M7E | Controlled LiveKit/ElevenLabs English validation produces bounded evidence or a documented failure |
| M7G | `stage7/m7g-acceptance-lock` | M7F | Full acceptance, security, CI wiring, and exit criteria are locked |

Each milestone is implemented and reviewed on its named branch, then integrated forward in the listed order. Use milestone-scoped commits with the `M7A`–`M7G` prefix; do not amend the approved design or remediation commits.

## M7A — Voice Foundation

### M7A.1 — Add the voice domain and `0007_voice_sessions_v1` migration

**Files:**

- Create `src/verbaops/voice/__init__.py`.
- Create `src/verbaops/voice/domain.py` and `src/verbaops/voice/models.py` for `VoiceSessionState`, `VoiceSessionRecord`, bootstrap DTOs, and strict request/response validation.
- Create `src/verbaops/voice/persistence.py` for the SQLAlchemy `VoiceSession` model and repository-facing projections.
- Create `migrations/versions/0007_voice_sessions_v1.py`.
- Modify `src/verbaops/conversations/persistence.py` and corresponding domain/repository mappings for `AgentRun.interaction_mode`, nullable `voice_session_id`, nullable `voice_turn_id`, and the partial uniqueness constraint required for voice provenance.
- Modify migration metadata imports so Alembic sees the new tables without changing historical migrations.
- Create `tests/voice/test_models.py`, `tests/migrations/test_voice_sessions_migration.py`, and `tests/postgres/voice/test_voice_session_schema.py`.

**Interfaces consumed:** existing `Base`, UUID/timestamp conventions, `AgentRun` status/lifecycle, `ActionRequestSummary`, `TrustedContext`, and migration `0006` state.

**Interfaces produced:** `VoiceSessionState`, `VoiceSessionRecord`, `VoiceSession` table, `0007_voice_sessions_v1`, and AgentRun voice provenance columns/constraints.

**Steps:**

- [ ] RED: write model tests for legal state transitions, invalid state values, required tenant/principal/customer/conversation/provider identities, and omitted role/token/raw-audio/provider-payload fields.
- [ ] RED: write AgentRun tests proving a voice run requires both session and turn IDs, a text run rejects both IDs, and a duplicate `(voice_session_id, voice_turn_id)` cannot be persisted.
- [ ] RED: write migration tests proving the new schema upgrades from the approved Stage 6 head, rolls back in the test harness if supported, and leaves historical Stage 6 rows unchanged.
- [ ] RED: write PostgreSQL constraint tests for non-null voice identity fields, legal status values, ended/connected timestamp consistency, and the one-running-AgentRun invariant.
- [ ] GREEN: implement the domain/persistence models and migration using existing naming, UUID, timezone, index, and constraint conventions.
- [ ] GREEN: add only the required AgentRun provenance fields and indexes; do not add a `voice_turns` table or persist role sets.
- [ ] GREEN: register metadata and repository projections without changing text-run defaults.
- [ ] REFACTOR: keep migration ownership isolated to `0007_voice_sessions_v1`; document all new durable fields in the module docstring.
- [ ] Run: `uv run pytest tests/voice/test_models.py tests/migrations/test_voice_sessions_migration.py -q`.
- [ ] Run: `uv run pytest tests/postgres/voice/test_voice_session_schema.py -m postgres -q`.
- [ ] Run: `uv run alembic upgrade head` in the repository’s configured migration test environment.
- [ ] Commit: `git commit -m "feat: add Stage 7 voice persistence"`.

### M7A.2 — Implement scoped voice-session repository and lifecycle service

**Files:**

- Create `src/verbaops/voice/repository.py`.
- Create `src/verbaops/voice/service.py`.
- Modify `src/verbaops/api/lifespan.py` and runtime resource construction only to register the service dependency; do not yet start a worker process.
- Create `tests/voice/test_voice_session_service.py` and `tests/postgres/voice/test_voice_session_lifecycle.py`.

**Interfaces consumed:** `VoiceSessionRecord`, SQLAlchemy transaction patterns from `src/verbaops/conversations/repository.py`, `TrustedContext`, and the approved lifecycle states.

**Interfaces produced:** `VoiceSessionService.create_customer_session`, scoped customer/worker reads, `mark_connecting`, `mark_connected`, `end_customer_session`, idempotent end behavior, and lifecycle errors.

**Steps:**

- [ ] RED: test creation with an optional conversation ID, customer-scoped reads, tenant/principal/customer matching, and non-enumerating foreign-session errors.
- [ ] RED: test `created → connecting → connected → ended`, repeated end idempotency, invalid transitions, reopen rejection, and timestamp behavior.
- [ ] RED: test session validity predicates for ended, expired, invalid, and wrong-scope sessions.
- [ ] RED: test transaction locking around state changes and duplicate lifecycle requests using a real PostgreSQL test.
- [ ] GREEN: implement repository methods with explicit scopes; never accept client-supplied tenant/principal/customer values.
- [ ] GREEN: implement service transition guards and bounded expiry checks using settings rather than a new revocation system.
- [ ] GREEN: make end safe to retry while preventing ended sessions from becoming active again.
- [ ] REFACTOR: centralize session validity checks so bootstrap, worker lookup, and transcript submission cannot diverge.
- [ ] Run: `uv run pytest tests/voice/test_voice_session_service.py -q`.
- [ ] Run: `uv run pytest tests/postgres/voice/test_voice_session_lifecycle.py -m postgres -q`.
- [ ] Commit: `git commit -m "feat: add Stage 7 voice session lifecycle"`.

### M7A.3 — Add typed voice settings and secret boundaries

**Files:**

- Modify `src/verbaops/config/settings.py` with a nested `VoiceSettings` section.
- Modify the settings fixture/factory files used by `tests/config/`.
- Create `tests/config/test_voice_settings.py`.

**Interfaces consumed:** existing `Settings`, `SecretStr`, environment prefix/nesting rules, and timeout conventions.

**Interfaces produced:** typed settings for LiveKit URL/key/secret, worker service token, STT/TTS provider identifiers, session/token TTLs, connection timeout, and bounded transcript/turn limits.

**Steps:**

- [ ] RED: test required secret validation, blank/whitespace secret rejection, safe `repr`, and redacted validation errors.
- [ ] RED: test URL normalization, positive bounded TTL/timeouts, provider identifier defaults, and explicit override behavior.
- [ ] RED: test that settings serialization cannot expose LiveKit secrets, worker tokens, or provider credentials.
- [ ] GREEN: add `VoiceSettings` with the repository’s existing Pydantic Settings style and no hard-coded production credentials.
- [ ] GREEN: make all voice services consume settings through dependency injection rather than module-level environment reads.
- [ ] REFACTOR: name limits by semantic purpose and keep all provider-specific identifiers configurable.
- [ ] Run: `uv run pytest tests/config/test_voice_settings.py -q`.
- [ ] Run: `uv run pytest tests/config -q`.
- [ ] Commit: `git commit -m "feat: configure Stage 7 voice services"`.

### M7A.4 — Mint narrow LiveKit customer tokens

**Files:**

- Create `src/verbaops/voice/livekit.py` implementing `LiveKitTokenIssuer`.
- Create `tests/voice/test_livekit_token.py`.
- Modify only the provider dependency manifest/lockfile during future implementation after verifying current official LiveKit documentation; do not hard-code a version in this plan.

**Interfaces consumed:** `VoiceSettings`, `LiveKitTokenIssuer`, server-generated session identities, and the existing secret boundary.

**Interfaces produced:** a fakeable token issuer that creates a server-owned room/participant identity, minimum publish/subscribe grants needed for the browser voice channel, and bounded expiry.

**Steps:**

- [ ] RED: test that caller-supplied room names, participant identities, grants, roles, and TTLs cannot override server values.
- [ ] RED: test minimum grants, short bounded expiry, issuer/audience configuration, and room-token-not-returned-on-failure behavior.
- [ ] RED: test no token or LiveKit secret appears in logs, exception strings, metrics, or serialized session records.
- [ ] GREEN: implement the official LiveKit token builder behind the narrow issuer protocol.
- [ ] GREEN: derive room and participant identity from the durable session and trusted principal, with collision-safe server IDs.
- [ ] REFACTOR: keep provider SDK details inside `livekit.py`; test the application against the protocol/fake rather than SDK objects.
- [ ] Run: `uv run pytest tests/voice/test_livekit_token.py -q`.
- [ ] Run: `uv run pytest tests/voice tests/config -q`.
- [ ] Commit: `git commit -m "feat: add bounded LiveKit voice tokens"`.

### M7A.5 — Add customer-only bootstrap and end APIs

**Files:**

- Create `src/verbaops/api/routes/voice_sessions.py`.
- Modify `src/verbaops/api/app.py` to include the voice session router.
- Modify `src/verbaops/api/dependencies.py` to inject the session service and token issuer through existing application dependencies.
- Create `tests/api/test_voice_sessions.py`.

**Interfaces consumed:** `POST /v1/conversations` customer authorization conventions, `VoiceSessionService`, `LiveKitTokenIssuer`, and the exact response contract above.

**Interfaces produced:**

- `POST /v1/voice/sessions` with optional `conversation_id` only.
- `POST /v1/voice/sessions/{voice_session_id}/end` with no role or identity body.
- Bootstrap response exactly matches `VoiceSessionBootstrap`: `voice_session_id`, `conversation_id`, `livekit_url`, `room_token`, `token_expires_at`, and `status=VoiceSessionState.CREATED`; room/participant identities remain server-owned and are not response fields.

**Steps:**

- [ ] RED: test CUSTOMER bootstrap succeeds and returns only the bounded session/transport response.
- [ ] RED: test CUSTOMER + SUPPORT_AGENT, CUSTOMER + SUPPORT_SUPERVISOR, and CUSTOMER + TENANT_ADMIN bootstrap succeeds but records no roles and produces a worker context with exactly CUSTOMER.
- [ ] RED: test support-only, supervisor-only, and tenant-admin-only bootstrap returns the existing authorization error shape without session enumeration.
- [ ] RED: test foreign conversation IDs, forged principal/tenant/customer/room/participant fields, arbitrary extra body fields, and invalid UUIDs are rejected safely.
- [ ] RED: test bounded `token_expires_at`/session expiry, `status=VoiceSessionState.CREATED` at bootstrap, end behavior, repeated end, cross-customer isolation, and ended-session bootstrap/worker rejection.
- [ ] GREEN: implement the two routes using trusted context and server-owned session state only.
- [ ] GREEN: apply `has_customer_authority` at bootstrap and preserve the original principal ID for audit only.
- [ ] GREEN: ensure no arbitrary roles enter the durable record, token, response, or worker request.
- [ ] REFACTOR: keep HTTP validation separate from lifecycle policy and preserve existing error mapping/non-enumeration conventions.
- [ ] Run: `uv run pytest tests/api/test_voice_sessions.py -q`.
- [ ] Run: `uv run pytest tests/api/test_authentication.py tests/api/test_request_context.py -q`.
- [ ] Run: `uv run pytest tests/api tests/voice -q`.
- [ ] Commit: `git commit -m "feat: expose customer-only voice sessions"`.

### M7A.6 — Add the dedicated Voice Worker authentication primitive

**Files:**

- Create `src/verbaops/voice/auth.py`.
- Modify `src/verbaops/api/dependencies.py` with `get_voice_worker_context`.
- Create `tests/api/test_voice_worker_auth.py`.

**Interfaces consumed:** `OpaqueCredential`, existing authentication provider patterns, typed worker secret setting, and FastAPI dependency injection.

**Interfaces produced:** `VoiceWorkerContext`, `authenticate_worker`, and a worker-only dependency that is not accepted by customer routes or normal browser auth.

**Steps:**

- [ ] RED: test correct worker credential succeeds only on the internal voice dependency.
- [ ] RED: test customer credentials, missing credentials, malformed credentials, and normal API tokens cannot authenticate as the worker.
- [ ] RED: test the worker context contains only the fixed service identity and no caller role set.
- [ ] RED: test secret values are absent from logs and error responses.
- [ ] GREEN: implement constant-time credential comparison using the existing provider abstraction where possible.
- [ ] GREEN: make the worker dependency reject browser/public route use and keep the internal route namespace distinct.
- [ ] REFACTOR: document that worker authentication authorizes service transport only; it does not define customer roles.
- [ ] Run: `uv run pytest tests/api/test_voice_worker_auth.py -q`.
- [ ] Run: `uv run pytest tests/api/test_authentication.py -q`.
- [ ] Commit: `git commit -m "feat: isolate Stage 7 worker authentication"`.

### M7A exit gate

- [ ] `voice_sessions` has no roles or arbitrary claims.
- [ ] Bootstrap is customer-authorized and server-owned.
- [ ] Composed roles are accepted only as a bootstrap fact and narrow to CUSTOMER for later worker execution.
- [ ] Supervisor/support/admin-only callers cannot bootstrap.
- [ ] Worker authentication is distinct from customer authentication.
- [ ] `uv run pytest tests/api tests/voice tests/config -q` passes, plus the PostgreSQL voice schema/lifecycle tests.
- [ ] Record the M7A commit IDs before starting M7B.

## M7B — Voice Worker and Final Transcript Boundary

### M7B.1 — Add AgentRuntime interaction mode and provenance

**Files:**

- Modify `src/verbaops/agent/context.py` with `InteractionMode` and explicit voice provenance.
- Modify `src/verbaops/agent/runtime.py` and `src/verbaops/agent/state.py` to accept the frozen runtime contract.
- Modify `src/verbaops/conversations/domain.py`, `repository.py`, and `service.py` to persist/load provenance.
- Create `tests/agent/test_voice_runtime.py`.
- Extend existing text runtime tests only where needed to prove unchanged behavior.

**Interfaces consumed:** current `AgentRuntime.run_turn`, `AgentContext`, `ConversationService.start_turn`, Stage 6 `ActionProposalService`, and current evaluation profile handling.

**Interfaces produced:** explicit text/voice provenance, voice-required ID validation, and a `VoiceTurnResult` adapter that includes existing `ActionRequestSummary` values without changing Stage 6 policy.

**Steps:**

- [ ] RED: test all existing text calls produce the same message/run behavior and reject voice provenance IDs.
- [ ] RED: test voice calls require a valid session ID and voice turn ID, preserve trusted principal identity, and store `interaction_mode="voice"`.
- [ ] RED: test presentation mode does not modify authorization roles, evaluation profiles, prompt policy, or Stage 6 lifecycle.
- [ ] RED: test action proposals returned to voice contain the existing IDs, state, fingerprint, safe summary, and next actor.
- [ ] GREEN: thread explicit provenance through runtime/context/repository layers without duplicating AgentRuntime.
- [ ] GREEN: keep the same CommerceClient, action registry, proposal service, and policy path used by text.
- [ ] REFACTOR: centralize validation of text-versus-voice provenance and keep `VoiceTurnResult` construction at the voice boundary.
- [ ] Run: `uv run pytest tests/agent/test_voice_runtime.py tests/agent/test_runtime.py -q`.
- [ ] Run: `uv run pytest tests/agent -q`.
- [ ] Commit: `git commit -m "feat: add voice runtime provenance"`.

### M7B.2 — Implement durable final-event idempotency

**Files:**

- Modify `src/verbaops/conversations/repository.py` and `service.py` for voice-turn lookup/claim/replay semantics.
- Modify `src/verbaops/agent/runtime.py` only as needed to return a replayable result from durable state.
- Create `src/verbaops/voice/idempotency.py` if a dedicated typed result/error boundary is useful.
- Create `tests/postgres/voice/test_final_turn_idempotency.py`.

**Interfaces consumed:** AgentRun unique/one-running constraints, durable `Message`/`AgentRun` records, `voice_turn_id`, and transaction/locking conventions.

**Interfaces produced:** deterministic final transcript behavior:

- first submission creates one user message and one AgentRun;
- duplicate while running returns a typed in-progress result/error without a second message/run;
- duplicate after completion returns the existing assistant/action result;
- duplicate after failure returns the bounded recorded failure and does not rerun;
- a new voice turn ID is required for a new attempt.

**Steps:**

- [ ] RED: add sequential first/duplicate tests for running, completed, and failed states.
- [ ] RED: add simultaneous PostgreSQL submissions proving one unique winner, one user message, one AgentRun, and one action proposal at most.
- [ ] RED: add retry-after-commit and unique-violation reload tests.
- [ ] RED: prove no in-memory cache is needed for correctness and that replayed results contain no new timestamps/IDs.
- [ ] GREEN: claim the turn inside the existing transaction with row/unique locking and reload the winner on conflict.
- [ ] GREEN: make response reconstruction read durable assistant/action state rather than rerunning the model or tools.
- [ ] GREEN: map running/completed/failed states to bounded internal outcomes that the worker can retry safely.
- [ ] REFACTOR: keep all idempotency decisions in the service/repository boundary rather than in the provider adapter.
- [ ] Run: `uv run pytest tests/postgres/voice/test_final_turn_idempotency.py -m postgres -q`.
- [ ] Run: `uv run pytest tests/agent/test_voice_runtime.py tests/postgres/voice -m postgres -q`.
- [ ] Commit: `git commit -m "feat: make voice final turns idempotent"`.

### M7B.3 — Add the strict internal final-transcript API

**Files:**

- Create `src/verbaops/api/routes/voice_transcripts.py`.
- Modify `src/verbaops/api/app.py` to include the internal route.
- Modify `src/verbaops/api/dependencies.py` to require `VoiceWorkerContext`.
- Create `tests/api/test_voice_transcripts.py`.

**Interfaces consumed:** `VoiceWorkerContext`, `VoiceFinalTranscriptRequest`, `VoiceSessionService`, `AgentRuntime`, idempotency service, and lifecycle validity checks.

**Interfaces produced:** `POST /internal/voice/sessions/{voice_session_id}/final-transcripts` with strict body, bounded output, and worker-only authorization.

**Steps:**

- [ ] RED: test valid worker auth, connected valid session, bounded transcript, valid voice turn ID, runtime invocation, and structured action summaries.
- [ ] RED: test missing/extra body fields, worker-supplied roles/identity/tenant/customer/conversation, oversized transcript, and invalid IDs.
- [ ] RED: test ended, expired, invalid, wrong-scope, and cross-customer sessions are rejected before runtime.
- [ ] RED: test composed caller roles become exactly CUSTOMER in the runtime call and cannot inherit support/supervisor/admin authority.
- [ ] RED: test duplicate running/completed/failed behavior through the HTTP boundary and no duplicate messages.
- [ ] GREEN: implement the route with worker dependency, durable session lookup, exact customer-only context reconstruction, and runtime invocation.
- [ ] GREEN: preserve the session’s original `principal_id` as proposer/audit identity while setting roles to `frozenset({Role.CUSTOMER})`.
- [ ] GREEN: return bounded typed errors and never echo secrets, role claims, or provider payloads.
- [ ] REFACTOR: keep HTTP adapter code free of authorization inference and make the reconstructed context construction auditable in one named function.
- [ ] Run: `uv run pytest tests/api/test_voice_transcripts.py -q`.
- [ ] Run: `uv run pytest tests/api/test_voice_sessions.py tests/api/test_voice_transcripts.py -q`.
- [ ] Commit: `git commit -m "feat: add the worker transcript boundary"`.

### M7B.4 — Normalize STT partial/final events

**Files:**

- Create `src/verbaops/voice/speech.py`.
- Create `tests/voice/test_speech_events.py`.
- Add fake STT fixtures under `tests/voice/fakes.py` or the repository’s existing fixture convention.

**Interfaces consumed:** `SpeechEvent`, `STTAdapter`, final-transcript endpoint, session/turn identity rules.

**Interfaces produced:** provider-independent partial/final normalization with one final submission per `voice_turn_id`.

**Steps:**

- [ ] RED: test partial events update memory-only state, do not persist, and do not call the API/runtime.
- [ ] RED: test a final event creates one normalized event with bounded transcript and a stable turn ID.
- [ ] RED: test repeated provider final events with the same turn ID are idempotent at the worker boundary.
- [ ] RED: test empty/whitespace/oversized final transcripts become safe failures without a Stage 6 action.
- [ ] GREEN: implement fake/provider-neutral normalization and final-event de-duplication as an optimization only; durable server idempotency remains authoritative.
- [ ] REFACTOR: ensure raw provider event payloads are not stored or emitted in application logs.
- [ ] Run: `uv run pytest tests/voice/test_speech_events.py -q`.
- [ ] Commit: `git commit -m "feat: normalize Stage 7 speech events"`.

### M7B.5 — Build the fakeable Voice Worker coordinator skeleton

**Files:**

- Create `src/verbaops/voice/worker.py`.
- Create `src/verbaops/voice/worker_protocols.py` if transport/STT/TTS protocols need separate ownership.
- Create `tests/voice/test_worker_coordinator.py`.
- Create `tests/architecture/test_voice_worker_boundaries.py`.

**Interfaces consumed:** fake transport, `STTAdapter`, final-transcript client, `TTSAdapter`, `VoiceSessionService`, and `VoiceWorkerContext`.

**Interfaces produced:** coordinator that can accept normalized events, submit finals, play bounded results, handle interruption, and expose no CommerceClient/ActionExecutor/policy import.

**Steps:**

- [ ] RED: test coordinator injection with fake transport/STT/TTS and no browser/provider connection.
- [ ] RED: test partial/final event routing and one API submission per final.
- [ ] RED: architecture test that worker modules do not import `CommerceClient`, `ActionExecutor`, or direct Stage 6 policy/executor modules.
- [ ] RED: test worker restart can recreate coordinator state from durable session/turn results rather than an in-memory role or action authority.
- [ ] GREEN: implement the coordinator as an adapter/orchestrator around the internal API and speech protocols.
- [ ] GREEN: keep provider-specific LiveKit/ElevenLabs code out of policy and conversation modules.
- [ ] REFACTOR: make lifecycle cleanup explicit for disconnect, ended session, cancellation, and provider errors.
- [ ] Run: `uv run pytest tests/voice/test_worker_coordinator.py tests/architecture/test_voice_worker_boundaries.py -q`.
- [ ] Run: `uv run pytest tests/voice tests/architecture -q`.
- [ ] Commit: `git commit -m "feat: add the fakeable Stage 7 worker"`.

### M7B exit gate

- [ ] Worker requests have exactly `voice_turn_id` and `transcript` in the body.
- [ ] Worker runtime context has original tenant/principal/customer from the durable session and exactly CUSTOMER role authority.
- [ ] Partial STT never reaches runtime or persistence.
- [ ] Final STT is durable and idempotent under sequential and concurrent duplicates.
- [ ] Voice Worker has no direct commerce or executor imports.
- [ ] `uv run pytest tests/api/test_voice_transcripts.py tests/voice tests/agent/test_voice_runtime.py -q` passes with PostgreSQL contract tests.

## M7C — Browser Voice Surface

### M7C.1 — Verify and add browser provider dependencies through official current documentation

**Files:**

- Modify `apps/web/package.json` and the appropriate pnpm lockfile only during implementation.
- Modify `apps/web/src/` only in later tasks, not as part of dependency selection.
- Add a short dependency rationale to the milestone change record if the repository convention requires it.

**Interfaces consumed:** current Next/React app, Node engine, pnpm version, official LiveKit browser package documentation, and the fake transport contract from M7B.

**Interfaces produced:** compatible browser packages for LiveKit client/components as needed, with no unverified version pin.

**Steps:**

- [ ] RED: record the current package manager/runtime constraints and verify the official package names/API used by the chosen LiveKit browser integration.
- [ ] GREEN: add only the packages needed for the browser transport and React integration; preserve lockfile reproducibility.
- [ ] REFACTOR: isolate provider imports behind a small browser transport adapter so component tests can use a fake.
- [ ] Run: `pnpm --dir apps/web install --frozen-lockfile`.
- [ ] Run: `pnpm --dir apps/web exec tsc --noEmit`.
- [ ] Commit: `git commit -m "build: add Stage 7 browser voice dependencies"`.

### M7C.2 — Add BFF bootstrap/end routes

**Files:**

- Create `apps/web/src/app/api/voice/sessions/route.ts`.
- Create `apps/web/src/app/api/voice/sessions/[voiceSessionId]/end/route.ts`.
- Create `apps/web/src/lib/server/voice-routes.ts` if shared forwarding/response validation is useful.
- Create route tests alongside the routes, following `apps/web/src/app/api/conversations/routes.test.ts` conventions.

**Interfaces consumed:** VerbaOps `POST /v1/voice/sessions` and end route, `forwardToVerbaOps`, server-only environment configuration, and the bounded bootstrap response.

**Interfaces produced:** fixed same-origin browser endpoints that forward only optional `conversation_id` on start and the path session ID on end.

**Steps:**

- [ ] RED: test server-only forwarding, allowed body fields, fixed upstream paths, exact `VoiceSessionBootstrap` response fields (`voice_session_id`, `conversation_id`, `livekit_url`, `room_token`, `token_expires_at`, `status`), upstream error mapping, and timeout behavior.
- [ ] RED: test no browser-provided identity, role, room, participant, token, or grant fields are forwarded.
- [ ] RED: test the returned room token is present only in the immediate response path and is never written to `localStorage`, `sessionStorage`, cookies, or logs.
- [ ] GREEN: implement the two BFF routes through the existing server-only forwarding helper.
- [ ] GREEN: validate the response shape and redact provider secrets in error/log paths.
- [ ] REFACTOR: keep upstream URL construction centralized and avoid exposing the VerbaOps base URL to the browser.
- [ ] Run: `pnpm --dir apps/web exec vitest run src/app/api/voice`.
- [ ] Run: `pnpm --dir apps/web exec tsc --noEmit`.
- [ ] Commit: `git commit -m "feat: add browser voice session BFF"`.

### M7C.3 — Add focused `VoicePanel` UI and transport state

**Files:**

- Create `apps/web/src/components/voice-panel.tsx`.
- Create `apps/web/src/components/voice-panel.test.tsx`.
- Create `apps/web/src/lib/voice-client.ts` with a fakeable transport interface.
- Modify `apps/web/src/components/chat.tsx` only to mount the focused panel and connect it to current conversation state.

**Interfaces consumed:** BFF routes, browser transport adapter, current Chat conversation state, existing action card rendering, and fake provider/test transport.

**Interfaces produced:** an exact browser `VoiceSessionBootstrap` type containing only `voice_session_id`, `conversation_id`, `livekit_url`, `room_token`, `token_expires_at`, and `status`, plus Start Voice/End Voice controls and state rendering for disconnected, connecting, connected, listening, user speaking, thinking, assistant speaking, interrupted, partial transcript, and error.

**Steps:**

- [ ] RED: test Start/End controls, disabled/busy transitions, fake connection success/failure, and cleanup on unmount.
- [ ] RED: test partial transcript is rendered as ephemeral text and is cleared/updated without altering durable chat messages.
- [ ] RED: test assistant speaking/interrupted/error state transitions and accessible status labels.
- [ ] RED: test no microphone hardware, LiveKit connection, or live provider is required for component tests.
- [ ] GREEN: implement a focused panel without redesigning Chat or duplicating action cards.
- [ ] GREEN: use server-created token/room response only for the current in-memory connection; do not persist tokens.
- [ ] GREEN: make transport and audio indicators injectable so the browser UI can remain provider-free in CI.
- [ ] REFACTOR: preserve the current `verbaops.conversationId` continuity convention and isolate voice-only state.
- [ ] Run: `pnpm --dir apps/web exec vitest run src/components/voice-panel.test.tsx`.
- [ ] Run: `pnpm --dir apps/web exec vitest run src/components src/app/api`.
- [ ] Run: `pnpm --dir apps/web exec tsc --noEmit`.
- [ ] Commit: `git commit -m "feat: add the browser voice panel"`.

### M7C.4 — Preserve text/voice conversation continuity

**Files:**

- Modify `apps/web/src/components/chat.tsx` and voice state hook/client files.
- Create `apps/web/src/components/voice-continuity.test.tsx`.

**Interfaces consumed:** existing conversation loading/message BFFs, sessionStorage conversation ID, voice bootstrap optional conversation ID, and end semantics.

**Interfaces produced:** text→voice, voice-created→text, reload, and new-conversation behavior with explicit transport cleanup.

**Steps:**

- [ ] RED: test starting voice from an existing text conversation uses the same conversation ID.
- [ ] RED: test a voice-created conversation can be loaded by text Chat after voice ends.
- [ ] RED: test reload restores conversation continuity but never restores an active token or live connection.
- [ ] RED: test New Conversation ends/clears voice transport and clears conversation identity according to current Chat behavior.
- [ ] GREEN: implement continuity using server conversation IDs and current browser storage conventions only.
- [ ] REFACTOR: make disconnect/reload cleanup deterministic and avoid stale session IDs after end.
- [ ] Run: `pnpm --dir apps/web exec vitest run src/components/voice-continuity.test.tsx src/components/chat.test.tsx`.
- [ ] Commit: `git commit -m "feat: preserve voice conversation continuity"`.

### M7C.5 — Add UI hint-safety and identity safety tests

**Files:**

- Create `apps/web/src/components/voice-hint-safety.test.tsx`.
- Modify `apps/web/src/components/action-request-card.tsx` only if a small shared read-only status adapter is required.

**Interfaces consumed:** server-loaded conversation/action state, voice partials, existing action card, and supervisor browser workflow.

**Interfaces produced:** UI behavior that treats voice/provider/browser hints as untrusted presentation input.

**Steps:**

- [ ] RED: test forged voice hints cannot mark an action succeeded/confirmed or show supervisor approval as complete.
- [ ] RED: test forged customer identity or role hints cannot alter displayed identity without a fresh server response.
- [ ] RED: test partial transcript and provider metadata remain memory-only and cannot create durable action state.
- [ ] GREEN: render only server-authoritative action state and bounded worker outcomes.
- [ ] REFACTOR: keep supervisor actions bound to existing browser routes and auth; do not add voice approval controls.
- [ ] Run: `pnpm --dir apps/web exec vitest run src/components/voice-hint-safety.test.tsx`.
- [ ] Commit: `git commit -m "test: lock browser voice hint safety"`.

### M7C.6 — Add provider-free browser smoke coverage

**Files:**

- Create `apps/web/tests/smoke/stage7-voice.spec.ts`.
- Modify `apps/web/playwright.config.ts` only if a named provider-free mock fixture is needed.
- Create or modify test-only mock transport/server fixtures under `apps/web/tests/fixtures/`.

**Interfaces consumed:** BFF routes, fake voice transport, current Next test server, and existing backend stub.

**Interfaces produced:** browser smoke coverage for Start Voice, End Voice, partial state, error state, reload, and action display without microphone/provider credentials.

**Steps:**

- [ ] RED: write smoke cases for start/end, partial transcript, assistant speaking/interrupted state, reload cleanup, and action card rendering.
- [ ] RED: assert no token is stored in browser storage or exposed in unrelated DOM attributes.
- [ ] GREEN: add deterministic route/transport mocks and run with one worker as existing Playwright configuration requires.
- [ ] REFACTOR: keep live-provider validation out of Playwright CI.
- [ ] Run: `pnpm --dir apps/web exec playwright test tests/smoke/stage7-voice.spec.ts`.
- [ ] Run: `pnpm --dir apps/web exec vitest run`.
- [ ] Commit: `git commit -m "test: add provider-free browser voice smoke"`.

### M7C exit gate

- [ ] Browser can start/end a mocked session through fixed BFF routes.
- [ ] Tokens never enter browser storage, logs, or durable application state.
- [ ] Existing text Chat and action cards still work.
- [ ] Reload/new conversation cannot resurrect an active transport or gate.
- [ ] Provider-free Vitest and Playwright smoke pass.

## M7D — Voice Action Summaries and Confirmation

### M7D.1 — Format deterministic server-owned speech summaries

**Files:**

- Create `src/verbaops/voice/actions.py`.
- Create `tests/voice/test_action_summaries.py`.
- Modify `src/verbaops/actions/decisions.py` only if a read-only projection helper is needed; do not alter Stage 6 decision semantics.

**Interfaces consumed:** `ActionRequestView`, `ActionRequestSummary`, `ActionType`, `ActionState`, proposal fingerprint, stored proposal values, and existing safe summary rules.

**Interfaces produced:** `ActionSpeechSummaryFormatter.format(view) -> VoiceActionPrompt` for all five action types.

**Steps:**

- [ ] RED: test deterministic summaries for exactly `reschedule_delivery`, `cancel_order`, `initiate_return`, `create_support_ticket`, and `request_refund`.
- [ ] RED: test `reschedule_delivery` uses stored `order_id`, `delivery_slot_id`, and only authoritative safe material already present in the durable projection, such as `target_service_date` or delivery-window fields; never infer a human date/time from a slot UUID.
- [ ] RED: test `cancel_order` uses the stored order target and consequence wording without claiming cancellation completion before Stage 6 verifies it.
- [ ] RED: test `initiate_return` uses stored `order_id`, each `items[].order_item_id`, each `items[].quantity`, and `reason`.
- [ ] RED: test `create_support_ticket` uses stored optional `order_id`, `category`, `subject`, and bounded `description`.
- [ ] RED: test `request_refund` uses stored `order_id`, `amount`, trusted `currency_code` when available from the durable decision projection, and `reason`; refund request/approval is never described as payment settlement.
- [ ] RED: test summaries use only existing `ActionRequestView.proposal`, `ActionRequestView.currency_code`, `ActionRequestView.safe_summary`, and persisted safe material; do not invent proposal fields, dates, historical snapshot values, or payment completion.
- [ ] RED: test pending supervisor approval says approval is required and offers no voice supervisor operation.
- [ ] GREEN: implement server-side formatting for exactly the five frozen Stage 6 `ActionType` values with bounded field labels, relevant consequences, and no foreign action semantics.
- [ ] GREEN: expose only read-only action prompt data to the worker/browser.
- [ ] REFACTOR: keep grammar/provider presentation separate from Stage 6 action state.
- [ ] Run: `uv run pytest tests/voice/test_action_summaries.py -q`.
- [ ] Commit: `git commit -m "feat: add deterministic voice action summaries"`.

### M7D.2 — Implement exact spoken confirmation parsing

**Files:**

- Create `src/verbaops/voice/confirmation.py`.
- Create `tests/voice/test_confirmation.py`.

**Interfaces consumed:** normalized final transcripts and the exact confirmation vocabulary in the approved spec.

**Interfaces produced:** `ConfirmationIntent` parser accepting exactly positive `confirm`, `yes, confirm`, `go ahead`, and `proceed` forms and negative `cancel`, `reject`, and `no` forms with only approved case, surrounding-whitespace, and basic terminal-punctuation normalization. Bare `yes` is ambiguous and non-authorizing.

**Steps:**

- [ ] RED: test accepted positive phrases exactly: `confirm`, `yes, confirm`, `go ahead`, and `proceed`, plus only case, surrounding-whitespace, and explicitly supported basic terminal-punctuation variants.
- [ ] RED: test accepted negative phrases exactly: `cancel`, `reject`, and `no`, plus only the same approved normalization variants.
- [ ] RED: test `yes`, `yeah`, `sure`, `maybe`, `I guess`, `probably`, arbitrary longer statements, and Arabic equivalents are ambiguous/non-authorizing.
- [ ] RED: test no fuzzy matching, semantic similarity, or LLM classification is used.
- [ ] RED: test parser never decides an action without a bound pending gate.
- [ ] GREEN: implement the exact normalized grammar; bare `yes` remains non-authorizing and no semantic LLM classification, fuzzy matching, or additional phrase is accepted.
- [ ] REFACTOR: keep accepted vocabulary auditable and English-first while preserving bounded Arabic plumbing where the spec requires it.
- [ ] Run: `uv run pytest tests/voice/test_confirmation.py -q`.
- [ ] Commit: `git commit -m "feat: add exact voice confirmation grammar"`.

### M7D.3 — Add ephemeral pending confirmation state

**Files:**

- Create `src/verbaops/voice/pending_confirmation.py`.
- Create `tests/voice/test_pending_confirmation.py`.

**Interfaces consumed:** `PendingVoiceConfirmation`, action prompt, session lifecycle, and proposal fingerprint.

**Interfaces produced:** session/action/fingerprint-bound in-memory gate with explicit invalidation on interruption, end, reconnect, stale action, and mismatch.

**Steps:**

- [ ] RED: test a gate is bound to exactly one session, action ID, and proposal fingerprint.
- [ ] RED: test opposite decisions, stale fingerprints, changed actions, ended sessions, and new sessions cannot reuse a gate.
- [ ] RED: test worker restart always destroys `PendingVoiceConfirmation`, including a previously armed gate; no completed-playout marker or other durable authority may recreate it.
- [ ] RED: test no Redis or durable confirmation authority is introduced without a separate design review.
- [ ] GREEN: implement the ephemeral state machine and invalidation operations.
- [ ] REFACTOR: keep durable Stage 6 action state authoritative and make the gate an intent/presentation guard only.
- [ ] Run: `uv run pytest tests/voice/test_pending_confirmation.py -q`.
- [ ] Commit: `git commit -m "feat: add session-bound voice confirmation state"`.

### M7D.4 — Enforce full-playout-before-arm

**Files:**

- Create `src/verbaops/voice/playout.py`.
- Create `tests/voice/test_playout_gate.py`.
- Modify `src/verbaops/voice/worker.py` to use playout lifecycle events.

**Interfaces consumed:** `TTSAdapter`, `PlayoutHandle`, `PendingVoiceConfirmation`, action summary formatter, interruption/cancellation events.

**Interfaces produced:** gate state transitions distinguishing TTS generation, first audio, actual completion, interruption, and cancellation.

**Steps:**

- [ ] RED: test TTS generation and first audio do not arm the gate.
- [ ] RED: test complete playout arms the gate and only then accepts exact positive/negative confirmation.
- [ ] RED: test interruption/cancellation before completion clears the gate.
- [ ] RED: test `confirm` after an interrupted summary performs zero Stage 6 decisions.
- [ ] RED: test an assistant response that is not a confirmation summary never arms a gate.
- [ ] GREEN: implement playout state with an explicit completion signal and cancellation path.
- [ ] GREEN: ensure barge-in cancels audio and invalidates pending confirmation before any decision call.
- [ ] REFACTOR: keep audio timing metrics separate from action state and avoid deriving completion from provider stream arrival heuristics.
- [ ] Run: `uv run pytest tests/voice/test_playout_gate.py -q`.
- [ ] Commit: `git commit -m "feat: require complete voice confirmation playout"`.

### M7D.5 — Bridge customer confirmation to existing Stage 6 decisions

**Files:**

- Create `src/verbaops/voice/decision_bridge.py`.
- Create `tests/voice/test_decision_bridge.py`.
- Modify `src/verbaops/actions/decisions.py` only to expose a typed application-service call if the existing service does not provide one; preserve self-approval and scope rules.

**Interfaces consumed:** Stage 6 customer confirmation service, exact action ID/fingerprint/customer scope, `ConfirmationIntent`, and durable action states.

**Interfaces produced:** voice customer decision bridge that calls the existing Stage 6 decision path and does not expose public direct execution.

**Steps:**

- [ ] RED: test exact fingerprint/customer/session binding, positive confirmation, negative rejection/withdrawal, same-decision replay, opposite race, stale action, and changed action.
- [ ] RED: test awaiting supervisor approval rejects positive voice confirmation and leaves the action awaiting approval.
- [ ] RED: test the bridge cannot execute CommerceClient directly and cannot bypass Stage 6 self-approval/authorization rules.
- [ ] GREEN: call the existing Stage 6 decision service with the original principal identity and CUSTOMER-only trusted context.
- [ ] GREEN: map durable decision results back to bounded spoken outcomes.
- [ ] REFACTOR: keep voice parsing/playout separate from action policy and execution.
- [ ] Run: `uv run pytest tests/voice/test_decision_bridge.py tests/actions -q`.
- [ ] Commit: `git commit -m "feat: bridge voice confirmation to Stage 6"`.

### M7D.6 — Lock supervisor boundary

**Files:**

- Create `tests/voice/test_supervisor_boundary.py`.
- Modify `src/verbaops/voice/actions.py` only for read-only approval-required wording.

**Interfaces consumed:** Stage 6 approval states and existing browser supervisor routes.

**Interfaces produced:** explicit voice behavior for high-risk actions: waiting for supervisor approval, no supervisor operation in voice, and post-browser-approval summary replay before customer confirmation.

**Steps:**

- [ ] RED: test voice cannot approve, reject supervisor review, or impersonate a supervisor.
- [ ] RED: test browser supervisor approval changes durable state and the next voice summary reflects the new state.
- [ ] RED: test the post-approval summary must fully play before customer confirmation is accepted.
- [ ] GREEN: render approval-required outcomes and route all actual approval through existing browser supervisor workflow.
- [ ] REFACTOR: add no new supervisor endpoint, role, or voice grant.
- [ ] Run: `uv run pytest tests/voice/test_supervisor_boundary.py tests/actions -q`.
- [ ] Commit: `git commit -m "test: lock the voice supervisor boundary"`.

### M7D exit gate

- [ ] Every action type has a deterministic stored-value summary.
- [ ] Confirmation grammar is exact and bounded.
- [ ] Full playout is required before arming.
- [ ] Interruption leaves no armed gate.
- [ ] Voice customer confirmation uses the existing Stage 6 decision service.
- [ ] Supervisor approval remains browser-only.

## M7E — Turn Safety, Concurrency, Recovery, and Failure Semantics

### M7E.1 — Use supported VAD/turn detection boundaries

**Files:**

- Modify `src/verbaops/voice/worker.py` and provider adapter interfaces as needed.
- Create `tests/voice/test_turn_detection.py`.

**Interfaces consumed:** normalized speech events, deterministic fake turn/VAD events, playout lifecycle, interruption/cancellation events, and the existing worker protocols. If LiveKit type/API knowledge is needed to define the abstraction, verify current official LiveKit documentation during M7E implementation; do not defer the contract to M7F.

**Interfaces produced:** turn detection integration that does not implement custom timing or bespoke speech segmentation.

**Steps:**

- [ ] RED: test provider-neutral start/stop/partial/final event sequences with fake timing.
- [ ] RED: test silence, interruption, cancellation, and end-session events do not generate phantom finals.
- [ ] GREEN: implement provider-independent turn semantics for speech started, partial transcript, final transcript, assistant playout, interruption, silence/no-final, cancellation, and confirmation-gate clearing. Do not make this milestone depend on a future provider selection.
- [ ] REFACTOR: retain fake event injection and keep timing values in settings.
- [ ] Run: `uv run pytest tests/voice/test_turn_detection.py -q`.
- [ ] Commit: `git commit -m "feat: integrate supported voice turn detection"`.

### M7E.2 — Handle barge-in and interrupted assistant responses

**Files:**

- Modify `src/verbaops/voice/worker.py`, `playout.py`, and `pending_confirmation.py`.
- Create `tests/voice/test_barge_in.py`.

**Interfaces consumed:** playout gate, TTS cancellation, STT partial/final events, durable AgentRun state.

**Interfaces produced:** safe barge-in handling where ordinary response audio can be interrupted, confirmation summaries clear the gate, and interrupted assistant speech has no false durable completion.

**Steps:**

- [ ] RED: test ordinary response interruption cancels playout and leaves durable message/action state authoritative.
- [ ] RED: test confirmation-summary interruption clears pending gate and later confirm does nothing.
- [ ] RED: test partial speech during assistant audio is memory-only until a valid new final event.
- [ ] GREEN: implement cancellation/invalidation ordering before accepting new turn input.
- [ ] REFACTOR: make event ordering observable through safe state labels, not raw audio logs.
- [ ] Run: `uv run pytest tests/voice/test_barge_in.py tests/voice/test_playout_gate.py -q`.
- [ ] Commit: `git commit -m "feat: make voice barge-in safe"`.

### M7E.3 — Enforce voice/text one-running-turn concurrency

**Files:**

- Modify conversation/voice repository transaction code.
- Create `tests/postgres/voice/test_voice_text_concurrency.py`.

**Interfaces consumed:** existing one-running-AgentRun partial unique constraint, voice-turn idempotency, text message route, and PostgreSQL transaction fixtures.

**Interfaces produced:** one-winner semantics across voice and text for the same conversation without an in-memory queue.

**Steps:**

- [ ] RED: run simultaneous voice and text submissions and assert exactly one running turn, no duplicate action proposal, and bounded busy/retry outcome for the loser.
- [ ] RED: run voice/voice different-turn concurrency and duplicate same-turn concurrency.
- [ ] RED: test transaction rollback leaves no orphan user message or misleading worker gate.
- [ ] GREEN: reuse current database constraint/locking and map conflicts to typed outcomes.
- [ ] REFACTOR: avoid application-level locks that would fail across workers.
- [ ] Run: `uv run pytest tests/postgres/voice/test_voice_text_concurrency.py -m "postgres and concurrency" -q`.
- [ ] Run: `uv run pytest tests/postgres/stage6 -m postgres -q`.
- [ ] Commit: `git commit -m "feat: enforce voice and text turn safety"`.

### M7E.4 — Test browser/voice decision races

**Files:**

- Create `tests/postgres/voice/test_voice_decision_races.py`.
- Modify `src/verbaops/voice/decision_bridge.py` only if a typed conflict mapping is needed.

**Interfaces consumed:** Stage 6 action decision transaction, pending gate, browser decision routes, proposal fingerprint.

**Interfaces produced:** safe race behavior for confirm/confirm, confirm/reject withdrawal, browser/voice concurrent decisions, and stale action state.

**Steps:**

- [ ] RED: test simultaneous voice confirms result in one durable decision.
- [ ] RED: test simultaneous voice confirm and browser reject/withdraw produce one valid winner and no duplicate execution.
- [ ] RED: test browser supervisor approval racing with voice customer confirmation cannot bypass approval state.
- [ ] RED: test existing Stage 6 lock/self-approval rules remain the only decision authority.
- [ ] GREEN: use existing action row/fingerprint locking and map losers to replay/current-state outcomes.
- [ ] REFACTOR: do not add a second decision lock model for voice.
- [ ] Run: `uv run pytest tests/postgres/voice/test_voice_decision_races.py -m "postgres and critical_race" -q`.
- [ ] Run: `uv run pytest tests/postgres/stage6 -m postgres -q`.
- [ ] Commit: `git commit -m "feat: protect voice decision races"`.

### M7E.5 — Define reconnect and session-end behavior

**Files:**

- Modify `src/verbaops/voice/worker.py`, service, and browser voice client.
- Create `tests/voice/test_reconnect.py`.

**Interfaces consumed:** durable session lifecycle, conversation continuity, pending confirmation, provider transport events.

**Interfaces produced:** valid reconnect behavior that preserves durable conversation/action state, clears unsafe ephemeral gates as specified, and rejects ended/expired sessions.

**Steps:**

- [ ] RED: test disconnect/reconnect clears an uncompleted confirmation gate.
- [ ] RED: test a valid reconnect can resume the same session only within bounded validity and preserves durable messages/action state.
- [ ] RED: test ended/expired sessions cannot reconnect or submit finals.
- [ ] RED: test a new session on the same conversation does not inherit stale transport token/gate state.
- [ ] GREEN: implement explicit reconnect/session-end transitions and safe state reload.
- [ ] REFACTOR: keep durable conversation continuity separate from ephemeral provider connection state.
- [ ] Run: `uv run pytest tests/voice/test_reconnect.py tests/voice/test_pending_confirmation.py -q`.
- [ ] Commit: `git commit -m "feat: make voice reconnect lifecycle safe"`.

### M7E.6 — Test worker crash/restart recovery

**Files:**

- Modify `src/verbaops/voice/worker.py` recovery path.
- Create `tests/voice/test_worker_recovery.py`.

**Interfaces consumed:** durable AgentRun/action/message state, idempotent final submission, playout/pending gate state, fake worker lifecycle.

**Interfaces produced:** restart-safe coordinator recovery with no duplicate action execution and no unsafe confirmation gate.

**Steps:**

- [ ] RED: test crash before final submission; final retry is accepted once.
- [ ] RED: test crash after final commit but before response; retry replays the result without duplicate message/action.
- [ ] RED: test crash after action creation before summary; restart reads durable action and formats summary without executing again.
- [ ] RED: test crash after summary generation before full playout; restart does not assume confirmation was armed.
- [ ] RED: test `test_restart_after_armed_confirmation_requires_summary_replay`: after a complete summary arms an ephemeral gate and the worker crashes before customer confirmation, durable `ActionRequest` remains `awaiting_confirmation`, the old gate is gone, immediate `confirm` does not decide, the current exact summary is replayed completely, and only a subsequent accepted confirmation calls Stage 6.
- [ ] RED: test crash during/after decision execution returns authoritative Stage 6 state.
- [ ] GREEN: implement recovery as durable lookup/replay plus unconditional gate invalidation. A worker restart always destroys `PendingVoiceConfirmation`, including a previously armed gate. After restart, load the durable current `ActionRequest`, validate it remains customer-confirmable, reconstruct the current deterministic summary, speak it completely, wait for uninterrupted full playout, and only then create/arm a new ephemeral gate.
- [ ] GREEN: never reconstruct an armed gate from `AgentRun`, `ActionRequest`, browser state, LiveKit state, worker memory, or a persisted playout-complete marker; do not add a durable playout-authority column/table or Redis confirmation authority.
- [ ] REFACTOR: make crash points explicit in fake tests and keep recovery provider-free.
- [ ] Run: `uv run pytest tests/voice/test_worker_recovery.py tests/postgres/voice/test_final_turn_idempotency.py -q`.
- [ ] Commit: `git commit -m "feat: make voice worker recovery idempotent"`.

### M7E.7 — Define bounded provider/backend failure behavior

**Files:**

- Modify `src/verbaops/voice/worker.py`, error models, and browser state mapping.
- Create `tests/voice/test_failures.py`.

**Interfaces consumed:** STT/TTS/LiveKit adapter errors, VerbaOps HTTP errors, AgentRuntime/LLM failures, durable lifecycle, browser error state.

**Interfaces produced:** bounded failure outcomes that never invent success, never arm unsafe confirmation, and preserve durable state truth.

**Steps:**

- [ ] RED: test STT timeout/provider failure, TTS failure, LiveKit disconnect, VerbaOps API failure, AgentRuntime/LLM failure, and action backend failure.
- [ ] RED: test errors do not fabricate an assistant result, successful action, refund settlement, or confirmation gate.
- [ ] RED: test retry policies are bounded and idempotent; no unbounded worker retry loop.
- [ ] GREEN: implement typed failure mapping, session end/error code updates, and browser-safe messages.
- [ ] REFACTOR: log correlation IDs and codes only; exclude transcripts where not needed, secrets, tokens, raw audio, and provider payloads.
- [ ] Run: `uv run pytest tests/voice/test_failures.py -q`.
- [ ] Run: `uv run pytest tests/api/test_errors.py tests/voice -q`.
- [ ] Commit: `git commit -m "feat: bound Stage 7 voice failures"`.

### M7E exit gate

- [ ] Duplicate finals, voice/text turns, decision races, interruption, reconnect, restart, and provider failures all have provider-free regression tests.
- [ ] No unsafe gate survives interruption, disconnect, restart, stale fingerprint, or ended session.
- [ ] No duplicate Stage 6 execution occurs under supported races/retries.
- [ ] Existing Stage 6 concurrency tests remain green.

## M7F — Controlled Provider Validation

### M7F.1 — Wire real provider adapters behind existing protocols

**Files:**

- Create `src/verbaops/voice/providers/livekit_worker.py`.
- Create `src/verbaops/voice/providers/elevenlabs_stt.py`.
- Create `src/verbaops/voice/providers/elevenlabs_tts.py`.
- Modify `pyproject.toml` and `uv.lock` only after checking current official LiveKit Agents/ElevenLabs documentation and selecting compatible ranges.
- Modify `Dockerfile`/runtime command only if the approved local/demo worker process requires it; keep production deployment out of scope.
- Create provider adapter tests using contract fakes/mocks, never live credentials in normal CI.

**Interfaces consumed:** `STTAdapter`, `TTSAdapter`, `PlayoutHandle`, LiveKit session/token boundary, fake worker coordinator, and current secret settings.

**Interfaces produced:** real provider implementations for controlled manual/local validation, with no policy or authorization logic in provider modules.

**Steps:**

- [ ] RED: run provider contract tests against fakes that model official event/error shapes before adding SDK-specific code.
- [ ] RED: test missing/invalid credentials fail at startup or connection with bounded errors and no secret leakage.
- [ ] GREEN: implement LiveKit Python worker transport, ElevenLabs Scribe v2 Realtime STT adapter, and ElevenLabs low-latency TTS/Flash v2.5 adapter where supported.
- [ ] GREEN: wire the maintained real-provider turn/VAD implementation selected from current official LiveKit documentation, including Silero VAD or LiveKit turn detection only if required/supported, and map it into the provider-independent M7E event semantics; do not build custom VAD timing.
- [ ] REFACTOR: preserve the same application protocols used by provider-free tests.
- [ ] Run: `uv run pytest tests/voice/providers -q`.
- [ ] Run: `uv run pytest tests/voice tests/api -q` without live credentials.
- [ ] Commit: `git commit -m "feat: add Stage 7 provider adapters"`.

### M7F.2 — Add local/demo runtime wiring

**Files:**

- Modify `src/verbaops/api/lifespan.py`/runtime resources if shared dependencies need explicit worker construction.
- Create a narrowly scoped worker entrypoint under `src/verbaops/voice/worker_entrypoint.py` or the repository’s existing service entrypoint convention.
- Modify local Docker/compose/dev scripts only if needed to start the worker in a local/demo profile; do not add cloud/Kubernetes deployment.
- Create `tests/voice/test_worker_entrypoint.py`.

**Interfaces consumed:** provider adapters, existing VerbaOps/NovaCommerce local runtime, browser BFF, and typed environment settings.

**Interfaces produced:** reproducible local/demo command that starts API, worker, browser, and fake or configured Commerce dependencies without production infrastructure assumptions.

**Steps:**

- [ ] RED: test worker entrypoint dependency wiring with provider fakes and no external secrets.
- [ ] RED: test startup failure is bounded when required provider configuration is absent.
- [ ] GREEN: add local/demo wiring only, reusing current runtime conventions and avoiding duplicated database/Redis ownership.
- [ ] GREEN: keep a fake-provider mode available for normal development/CI.
- [ ] REFACTOR: document required local variables without committing secrets or real tokens.
- [ ] Run: `uv run pytest tests/voice/test_worker_entrypoint.py tests/voice -q`.
- [ ] Run: repository-local demo health/readiness command documented by the implementation.
- [ ] Commit: `git commit -m "feat: wire the local Stage 7 voice runtime"`.

### M7F.3 — Run bounded English end-to-end scenarios

**Files:**

- Create `docs/evaluation/stage7-realtime-voice-validation.md`.
- Create `scripts/run_stage7_voice_validation.py` or use the repository’s existing manual validation runner if one exists.
- Add test-only/manual scenario fixtures under `tests/acceptance/stage7/` if shared with M7G.

**Interfaces consumed:** real local/demo worker, browser, VerbaOps API, NovaCommerce test backend, controlled provider accounts, and scenario checklist.

**Interfaces produced:** scenario evidence for simple response, Commerce read, normal action proposal, full summary, spoken confirm, verified final result, withdrawal, barge-in, reconnect, and safe failure.

**Steps:**

- [ ] RED: define a scenario checklist with conversation/session/turn correlation IDs and expected durable outcomes.
- [ ] GREEN: run English scenarios in a controlled environment; record pass/fail, provider/model identifiers, configuration class, and bounded timing summaries.
- [ ] GREEN: verify action state in the authoritative backend after each scenario; do not use audible claims as proof.
- [ ] REFACTOR: remove or redact all tokens, secrets, raw audio, provider payloads, and unnecessary transcript data from the report.
- [ ] Run: `uv run python scripts/run_stage7_voice_validation.py --scenario smoke` or the exact manual runner command recorded by implementation.
- [ ] Commit: `git commit -m "docs: record Stage 7 English validation scenarios"`.

### M7F.4 — Measure latency and NFR-12

**Files:**

- Modify `src/verbaops/voice/observability.py` or the existing observability seam.
- Modify `docs/evaluation/stage7-realtime-voice-validation.md`.
- Create `tests/voice/test_latency_metrics.py`.

**Interfaces consumed:** event timestamps, existing observability configuration, provider/model labels, and bounded validation runner.

**Interfaces produced:** metrics for speech end → final transcript, final transcript → AgentRuntime, TTS generation → first audio, speech end → first audible response, and full turn completion.

**Steps:**

- [ ] RED: test metric names, missing timestamp handling, correlation labels, and secret/audio redaction.
- [ ] GREEN: record sample count, p50, p95, provider/model, environment, and test conditions in the validation report.
- [ ] GREEN: mark NFR-12 PASS only when p95 speech end → first audible response is ≤ 3 seconds under the declared conditions; otherwise report failure without weakening the gate.
- [ ] REFACTOR: keep metrics bounded and avoid transcript/audio content in labels.
- [ ] Run: `uv run pytest tests/voice/test_latency_metrics.py -q`.
- [ ] Run: `uv run python scripts/run_stage7_voice_validation.py --scenario latency` or the exact recorded implementation command.
- [ ] Commit: `git commit -m "docs: measure Stage 7 voice latency"`.

### M7F.5 — Validate bounded MSA/Egyptian/code-switch plumbing

**Files:**

- Modify `docs/evaluation/stage7-realtime-voice-validation.md`.
- Create `tests/voice/test_language_plumbing.py` if normalization/config behavior needs provider-free coverage.

**Interfaces consumed:** provider language configuration, transcript normalization, English-first worker path.

**Interfaces produced:** evidence that MSA, Egyptian Arabic, and code-switch inputs can be configured/transported without claiming Stage 7 multilingual quality.

**Steps:**

- [ ] RED: test bounded language/config selection and safe code-switch transport through fakes.
- [ ] GREEN: run a small plumbing-only manual set and label it explicitly as non-quality evidence.
- [ ] REFACTOR: do not add WER, dialect, or production provider-winner claims to Stage 7.
- [ ] Run: `uv run pytest tests/voice/test_language_plumbing.py -q` if created.
- [ ] Commit: `git commit -m "docs: record bounded Stage 7 language plumbing"`.

### M7F.6 — Enforce evidence hygiene

**Files:**

- Modify `docs/evaluation/stage7-realtime-voice-validation.md`.
- Modify `.gitignore` only if the existing repository convention lacks a safe ignored location for temporary local provider artifacts; do not add broad ignores.
- Create a validation checklist test or script under `scripts/` if needed.

**Interfaces consumed:** validation report, local provider environment, repository artifact conventions.

**Interfaces produced:** exact report location `docs/evaluation/stage7-realtime-voice-validation.md`, with no raw audio, secrets, access tokens, or unbounded provider dumps.

**Steps:**

- [ ] RED: add a report hygiene check for secret-like strings, token fields, raw audio paths, and provider payload dumps.
- [ ] GREEN: record only bounded scenario outcomes, timing aggregates, versions/identifiers necessary for reproducibility, and failure explanations.
- [ ] GREEN: keep large local recordings outside the repository and delete temporary credential-bearing files after validation.
- [ ] REFACTOR: make the report understandable without exposing customer data or credentials.
- [ ] Run: `uv run python scripts/check_stage7_validation_report.py` if created.
- [ ] Commit: `git commit -m "docs: enforce Stage 7 validation evidence hygiene"`.

### M7F exit gate

- [ ] Real provider validation is manual/local/controlled only.
- [ ] Provider-free tests remain the normal CI path.
- [ ] English scenarios and failure cases are recorded with authoritative backend verification.
- [ ] Latency evidence states sample/p50/p95/provider/model/environment and NFR-12 result.
- [ ] MSA/Egyptian/code-switch evidence is plumbing-only and does not cross the Stage 8 boundary.
- [ ] The validation report contains no secrets, raw audio, access tokens, or arbitrary provider dumps.

## M7G — Acceptance Lock and CI Wiring

### M7G.1 — Add deterministic application-boundary acceptance tests

**Files:**

- Create `tests/acceptance/stage7/conftest.py`.
- Create `tests/acceptance/stage7/runtime.py`.
- Create `tests/acceptance/stage7/test_voice_workflows.py`.
- Create `tests/acceptance/stage7/test_voice_security.py`.
- Create `tests/acceptance/stage7/test_voice_races.py`.

**Interfaces consumed:** full fake provider stack, FastAPI app, browser BFF contract, Voice Worker, Stage 6 action lifecycle, and PostgreSQL fixtures where required.

**Interfaces produced:** end-to-end provider-free acceptance coverage across browser bootstrap, worker identity reconstruction, STT/runtime/TTS flow, action summaries, confirmation, interruption, reconnect, reload, and failures.

**Steps:**

- [ ] RED: test trusted customer bootstrap, server-owned identities, original principal audit identity, exact CUSTOMER-only worker roles, and worker auth.
- [ ] RED: test partial no-op, final once, duplicate final, continuity, spoken proposal, full arm, interruption, confirm, withdraw, awaiting approval, stale action, reconnect, and safe failure.
- [ ] RED: test an armed confirmation gate is destroyed by worker restart, immediate spoken `confirm` is non-authorizing after restart, and complete deterministic summary replay is required before a new gate and later confirmation.
- [ ] RED: test browser reload/new session does not resurrect token/gate state and action cards reflect server truth.
- [ ] GREEN: compose the deterministic fake stack at the app boundary rather than mocking every internal function.
- [ ] GREEN: include PostgreSQL-backed cases for durable uniqueness, lifecycle, action state, and required races.
- [ ] REFACTOR: keep acceptance fixtures isolated from unrelated historical tests.
- [ ] Run: `uv run pytest tests/acceptance/stage7 -m agent_acceptance -q`.
- [ ] Commit: `git commit -m "test: add Stage 7 acceptance workflows"`.

### M7G.2 — Add dangerous security/concurrency acceptance cases

**Files:**

- Modify `tests/acceptance/stage7/test_voice_security.py` and `test_voice_races.py`.
- Create `tests/test_stage7_ci_contract.py` for command/wiring assertions if appropriate.

**Interfaces consumed:** all M7A–M7E security and concurrency contracts.

**Interfaces produced:** release-blocking regression coverage for role injection, cross-customer access, direct Commerce attempts, duplicate finals, session-end races, and voice/text/action races.

**Steps:**

- [ ] RED: test worker cannot inject roles, tenant, principal, customer, conversation, room, or provider metadata.
- [ ] RED: test composed caller roles narrow, support-only/supervisor-only/admin-only bootstrap fails, and no voice supervisor operation exists.
- [ ] RED: test cross-customer session/conversation/fingerprint access does not enumerate or execute.
- [ ] RED: test direct Commerce/ActionExecutor imports or calls from worker fail architecture checks.
- [ ] RED: test duplicate simultaneous final, voice/text, confirm/confirm, confirm/reject, session-end/submit, and worker restart races.
- [ ] RED: include the crash-after-armed-confirmation replay scenario and prove no persisted playout marker or previous worker memory restores spoken-confirmation authority.
- [ ] GREEN: close any contract gap revealed by these tests without weakening the approved boundary.
- [ ] REFACTOR: keep this suite explicit and small enough to be a release gate.
- [ ] Run: `uv run pytest tests/acceptance/stage7/test_voice_security.py tests/acceptance/stage7/test_voice_races.py -m "agent_acceptance or critical_race" -q`.
- [ ] Commit: `git commit -m "test: lock Stage 7 security and race contracts"`.

### M7G.3 — Add provider-free Playwright acceptance

**Files:**

- Modify `apps/web/tests/smoke/stage7-voice.spec.ts` or create `apps/web/tests/acceptance/stage7-voice.spec.ts`.
- Modify only test fixtures/configuration needed to supply deterministic BFF/backend mocks.

**Interfaces consumed:** browser VoicePanel, BFF routes, fake transport, current Playwright setup.

**Interfaces produced:** provider-free browser acceptance for start/end, partial/state transitions, reload, action card, interruption, success, unresolved/approval-required, and no-token-storage behavior.

**Steps:**

- [ ] RED: add the complete browser scenario matrix with no microphone, LiveKit, or provider credentials.
- [ ] GREEN: use deterministic network/transport mocks and assert visible state plus server request contracts.
- [ ] REFACTOR: keep live provider checks in M7F, not CI.
- [ ] Run: `pnpm --dir apps/web exec playwright test tests/smoke/stage7-voice.spec.ts`.
- [ ] Commit: `git commit -m "test: add Stage 7 browser acceptance"`.

### M7G.4 — Add focused Make targets

**Files:**

- Modify `Makefile` with focused targets:
  - `stage7-voice-contract` for provider-free Python voice/API/architecture tests;
  - `stage7-postgres-contract` for migration/lifecycle/idempotency/concurrency/decision-race tests;
  - `stage7-acceptance` for Python application acceptance and provider-free web smoke.
- Modify command documentation only if the repository already keeps command docs separate; do not modify README for this planning task.

**Interfaces consumed:** existing Make conventions and test markers.

**Interfaces produced:** reproducible milestone/CI commands that do not deselect Stage 6 or web checks.

**Steps:**

- [ ] RED: add command contract tests or dry-run checks proving each target includes the intended paths/markers.
- [ ] GREEN: implement grouped targets with stable commands, not one target per tiny test file.
- [ ] GREEN: ensure targets preserve provider-free defaults and require explicit opt-in for live validation.
- [ ] REFACTOR: use existing package-manager wrappers and avoid shell-specific assumptions where current Make conventions avoid them.
- [ ] Run: `make stage7-voice-contract`.
- [ ] Run: `make stage7-postgres-contract`.
- [ ] Run: `make stage7-acceptance`.
- [ ] Commit: `git commit -m "build: add Stage 7 verification targets"`.

### M7G.5 — Wire CI without weakening existing gates

**Files:**

- Modify `.github/workflows/ci.yml` with Stage 7 provider-free contract/acceptance jobs or steps.
- Modify CI helper configuration only if required by existing patterns.
- Create `tests/test_stage7_ci_contract.py` if command/job assertions are part of the repository’s test style.

**Interfaces consumed:** current quality, PostgreSQL, Stage 6, web-quality, web-smoke, Docker, and historical test jobs.

**Interfaces produced:** CI coverage for Stage 7 contracts with no live provider credentials and no deselection of existing checks.

**Steps:**

- [ ] RED: assert CI includes voice contract, PostgreSQL concurrency, and provider-free browser smoke coverage.
- [ ] RED: assert Stage 6 action contract, web quality/smoke, Docker, migration, and historical tests remain selected.
- [ ] GREEN: add appropriately scoped jobs/steps with required services and dependency caching consistent with current CI.
- [ ] GREEN: ensure no provider secret is needed by default and live validation is not accidentally run in CI.
- [ ] REFACTOR: keep CI names and artifacts bounded and useful for independent review.
- [ ] Run: `uv run pytest tests/test_stage7_ci_contract.py -q` if created.
- [ ] Run: `make check`.
- [ ] Run: `make stage6-action-contract stage6-postgres-contract stage6-acceptance`.
- [ ] Run: `make stage7-voice-contract stage7-postgres-contract stage7-acceptance`.
- [ ] Commit: `git commit -m "ci: add provider-free Stage 7 gates"`.

### M7G.6 — Perform final acceptance and document exit criteria

**Files:**

- Modify `docs/evaluation/stage7-realtime-voice-validation.md` with final bounded evidence references.
- Create `docs/superpowers/reviews/2026-10-07-verbaops-stage7-realtime-voice-review.md` only if the repository’s review convention requires a durable review record; otherwise use the pull request/review system.
- Do not modify the approved design spec except through a separately approved design review.

**Interfaces consumed:** all M7A–M7F outputs, CI results, migration status, provider validation report, and Stage 6 regression suite.

**Interfaces produced:** acceptance-lock evidence and a clear pass/fail decision for each Stage 7 exit criterion.

**Steps:**

- [ ] RED: run the complete deterministic acceptance matrix and list any unresolved failure without marking Stage 7 complete.
- [ ] GREEN: run all required checks and record commit IDs, migration head, provider-free results, controlled provider evidence, and known limitations.
- [ ] GREEN: confirm no voice supervisor/staff/admin authority, no persisted roles, no worker role field, no raw audio, and no roadmap/spec contradiction.
- [ ] GREEN: confirm Stage 5 remains `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE` and Stage 8 remains the multilingual quality boundary.
- [ ] REFACTOR: remove temporary artifacts and ensure the final report contains no secrets or customer data.
- [ ] Run: `make check`.
- [ ] Run: `make stage6-action-contract stage6-postgres-contract stage6-acceptance`.
- [ ] Run: `make stage7-voice-contract stage7-postgres-contract stage7-acceptance`.
- [ ] Run: `pnpm --dir apps/web exec vitest run`.
- [ ] Run: `pnpm --dir apps/web exec playwright test tests/smoke/stage7-voice.spec.ts`.
- [ ] Run: `git diff --check` and repository-specific migration/schema checks.
- [ ] Commit: `git commit -m "docs: lock Stage 7 realtime voice acceptance"`.

### M7G exit gate

- [ ] All required deterministic acceptance, security, race, browser, PostgreSQL, and CI contract tests pass.
- [ ] Existing Stage 6 and historical checks pass unchanged.
- [ ] The controlled provider report is complete, bounded, and honest about any failed quality/latency criterion.
- [ ] NFR-12 is marked PASS only if the measured p95 is ≤3 seconds under declared conditions.
- [ ] No implementation begins beyond the approved Stage 7 scope without a new human review.

## Cross-Milestone Verification Matrix

| Requirement/risk | M7A | M7B | M7C | M7D | M7E | M7F | M7G |
|---|---:|---:|---:|---:|---:|---:|---:|
| Customer-only bootstrap and exact CUSTOMER reconstruction | ✓ | ✓ |  |  | ✓ |  | ✓ |
| Principal identity preserved for audit/proposer identity | ✓ | ✓ |  | ✓ | ✓ |  | ✓ |
| No persisted role sets/arbitrary claims | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |
| Worker request has no role field | ✓ | ✓ |  |  | ✓ |  | ✓ |
| LiveKit bounded token/session lifecycle | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |
| Partial memory-only/final durable semantics |  | ✓ | ✓ |  | ✓ | ✓ | ✓ |
| Durable duplicate-final idempotency |  | ✓ |  |  | ✓ |  | ✓ |
| Stage 6 action lifecycle reuse |  | ✓ |  | ✓ | ✓ | ✓ | ✓ |
| Full-playout confirmation gate |  |  |  | ✓ | ✓ | ✓ | ✓ |
| No voice supervisor/staff/admin authority | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Voice/text and decision race safety |  |  |  | ✓ | ✓ |  | ✓ |
| Provider-free CI | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Controlled real-provider evidence |  |  |  |  |  | ✓ | ✓ |

# Stage 7 Completion Criteria Traceability

The matrix below is the completion lock for the approved Stage 7 design. M7F real-provider rows are controlled evidence, not permanent provider-free CI claims.

| # | Completion criterion | Implementing milestone(s) | Primary evidence/test | Permanent gate |
|---:|---|---|---|---|
| 1 | Real browser microphone → LiveKit → Voice Worker → STT works. | M7C/M7F/M7G | Controlled validation report; `apps/web/tests/smoke/stage7-voice.spec.ts` for the provider-free transport contract. | `stage7-acceptance` contract gate; real-provider proof remains controlled M7F evidence, not normal CI. |
| 2 | Explicit FINAL transcripts enter the existing AgentRuntime. | M7B/M7G | `tests/api/test_voice_transcripts.py`; `tests/acceptance/stage7/test_voice_workflows.py::test_final_transcript_enters_existing_agent_runtime`. | `stage7-voice-contract` / `stage7-acceptance` |
| 3 | Partial transcripts never enter durable business turns. | M7B/M7G | `tests/voice/test_speech_events.py::test_partial_event_never_submits_or_persists`; `tests/acceptance/stage7/test_voice_workflows.py::test_partial_transcript_is_ephemeral`. | `stage7-voice-contract` / `stage7-acceptance` |
| 4 | Responses synthesize and play through LiveKit. | M7B/M7C/M7F/M7G | `tests/voice/test_worker_coordinator.py`; controlled provider validation report; `apps/web/tests/smoke/stage7-voice.spec.ts`. | `stage7-voice-contract` / `stage7-acceptance`; real provider playback remains controlled M7F evidence. |
| 5 | Text and voice share one durable Conversation. | M7A/M7B/M7C/M7G | `apps/web/src/components/voice-continuity.test.tsx`; `tests/acceptance/stage7/test_voice_workflows.py::test_text_and_voice_share_conversation`. | `stage7-voice-contract` / `stage7-acceptance` |
| 6 | Trusted identity remains entirely server-derived. | M7A/M7B/M7G | `tests/api/test_voice_sessions.py`; `tests/api/test_voice_transcripts.py::test_worker_cannot_inherit_composed_roles`; `tests/acceptance/stage7/test_voice_security.py`. | `stage7-voice-contract` / `stage7-acceptance` |
| 7 | Voice Worker cannot independently mutate Commerce. | M7B/M7D/M7E/M7G | `tests/architecture/test_voice_worker_boundaries.py`; `tests/acceptance/stage7/test_voice_security.py::test_worker_has_no_direct_commerce_or_executor_access`. | `stage7-voice-contract` / `stage7-acceptance` |
| 8 | Model has no confirmation or execution authority. | M7B/M7D/M7G | `tests/voice/test_decision_bridge.py`; `tests/voice/test_confirmation.py`; `tests/acceptance/stage7/test_voice_security.py`. | `stage7-voice-contract` / `stage7-acceptance` |
| 9 | Action confirmation is bound to exact ActionRequest, proposal fingerprint, and customer. | M7D/M7E/M7G | `tests/voice/test_pending_confirmation.py`; `tests/voice/test_decision_bridge.py`; `tests/postgres/voice/test_voice_decision_races.py`. | `stage7-voice-contract` / `stage7-postgres-contract` / `stage7-acceptance` |
| 10 | Complete deterministic spoken summary must finish before confirmation is armed. | M7D/M7G | `tests/voice/test_playout_gate.py::test_full_summary_arms_only_after_complete_playout`. | `stage7-voice-contract` / `stage7-acceptance` |
| 11 | Interrupted summary cannot authorize an action. | M7D/M7E/M7G | `tests/voice/test_playout_gate.py::test_interrupted_summary_then_confirm_never_decides`; `tests/acceptance/stage7/test_voice_races.py`. | `stage7-voice-contract` / `stage7-acceptance` |
| 12 | Barge-in works. | M7C/M7E/M7G | `tests/voice/test_barge_in.py`; `apps/web/tests/smoke/stage7-voice.spec.ts`. | `stage7-voice-contract` / `stage7-acceptance` |
| 13 | High-risk actions preserve supervisor-before-customer ordering. | M7D/M7E/M7G | `tests/voice/test_supervisor_boundary.py`; `tests/acceptance/stage7/test_voice_security.py::test_voice_cannot_approve_supervisor_gate`. | `stage7-voice-contract` / `stage7-acceptance` |
| 14 | Ambiguous, duplicate, stale, and racing decisions remain Stage 6 safe. | M7B/M7D/M7E/M7G | `tests/postgres/voice/test_final_turn_idempotency.py`; `tests/postgres/voice/test_voice_decision_races.py`; `tests/voice/test_confirmation.py`. | `stage7-voice-contract` / `stage7-postgres-contract` / `stage7-acceptance` |
| 15 | Provider and worker failures cannot invent business success. | M7E/M7F/M7G | `tests/voice/test_failures.py`; `tests/voice/test_worker_recovery.py`; controlled failure scenarios in the validation report. | `stage7-voice-contract` / `stage7-acceptance`; controlled provider failures remain M7F evidence. |
| 16 | No raw audio is persisted. | M7A/M7B/M7F/M7G | `tests/postgres/voice/test_voice_session_schema.py`; `tests/architecture/test_voice_worker_boundaries.py`; validation-report hygiene check. | `stage7-voice-contract` / `stage7-postgres-contract` / `stage7-acceptance` |
| 17 | English real-provider path works end to end. | M7F | Controlled English scenario report in `docs/evaluation/stage7-realtime-voice-validation.md`. | Not normal CI; manual controlled M7F evidence only. |
| 18 | NFR-12 latency target is measured honestly. | M7F | `tests/voice/test_latency_metrics.py`; validation report with sample count, p50, p95, provider/model, environment, and pass/fail. | Provider-free metric contract in `stage7-voice-contract`; measured result remains controlled M7F evidence. |
| 19 | MSA, Egyptian Arabic, and code-switch checks provide bounded plumbing evidence only. | M7F | `tests/voice/test_language_plumbing.py`; bounded language-plumbing section of the validation report. | `stage7-voice-contract`; quality claims remain outside Stage 7 and are not CI gates. |
| 20 | Permanent provider-free Stage 7 CI protects final-transcript and action boundaries. | M7B/M7D/M7E/M7G | `Makefile` targets and `.github/workflows/ci.yml`; `tests/test_stage7_ci_contract.py`. | `stage7-voice-contract` / `stage7-postgres-contract` / `stage7-acceptance` |
| 21 | All pre-existing Stage 6 gates remain green. | M7G | Existing Stage 6 targets and regression suites. | `stage6-action-contract` / `stage6-postgres-contract` / `stage6-acceptance` |

## Fresh Self-Review Checklist Before Implementation Starts

- [ ] Spec coverage: every approved requirement in Sections 5–31 of the design is assigned to one or more M7A–M7G tasks.
- [ ] Security coverage: customer-only bootstrap, exact role narrowing, preserved principal identity, no role persistence, no worker role input, and browser-only supervisor workflow are explicit in tasks and tests.
- [ ] Interface coverage: session service, token issuer, worker auth, strict transcript request, runtime provenance, speech adapters, action summaries, confirmation parser, playout gate, decision bridge, BFF, and browser transport are named with owners.
- [ ] Frozen contract coverage: the bootstrap DTO is exactly `voice_session_id`, `conversation_id`, `livekit_url`, `room_token`, `token_expires_at`, and `status`; confirmation grammar excludes bare `yes`; and cross-milestone names/semantics require human approval to change.
- [ ] Data coverage: `voice_sessions` has no role set, raw audio, token, secret, or arbitrary provider JSON; `AgentRun` has only required provenance fields; migration is `0007_voice_sessions_v1`.
- [ ] Concurrency coverage: duplicate final, voice/text turn, decision races, session end/submit, and worker restart are all named with PostgreSQL/provider-free tests.
- [ ] Recovery coverage: every worker restart destroys `PendingVoiceConfirmation`, including an armed gate, and the crash-after-armed case requires full deterministic summary replay.
- [ ] Testing coverage: provider-free unit/contract/acceptance checks are separated from M7F controlled validation, and existing Stage 6/web/historical checks remain selected.
- [ ] Completion coverage: all 21 approved Stage 7 completion criteria appear in the traceability matrix with milestone, evidence/test, and permanent gate ownership.
- [ ] Operational coverage: observability fields, bounded failures, recovery, latency evidence, report location, and evidence hygiene are specified.
- [ ] Scope coverage: no Stage 7 implementation, production IdP revocation system, multilingual quality gate, provider failover, direct executor, custom transport, roadmap expansion, or unrelated refactor is included.
- [ ] Execution check: use `superpowers:executing-plans` with one primary agent only; stop for human review if implementation uncovers an ambiguity that changes an approved security or lifecycle decision.

Stage 7 implementation roadmap is ready for independent human review before M7A execution.
