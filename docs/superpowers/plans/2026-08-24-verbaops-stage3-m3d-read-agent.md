# First LangGraph Read-Only Agent Runtime Implementation Plan

> **For agentic workers:** Execute inline in this session with strict RED-GREEN TDD. The user explicitly requires single-agent execution; do not use subagents, subagent-driven-development, or a top-level agent abstraction.

**Goal:** Add one bounded text-only LangGraph runtime that uses the existing M3A gateway, M3B persistence lifecycle, M3C CommerceClient, and exactly five read-only tools.

**Architecture:** `AgentRuntime` validates input, starts and completes/fails a persisted turn through `ConversationService`, and invokes a directly-built LangGraph `StateGraph`. An immutable `AgentContext` carries trusted identity and dependencies outside mutable graph state. Graph nodes own model-call, tool-call validation, and sequential allowlisted execution; all trace writes use short independent transactions.

**Tech Stack:** Python 3.12, LangGraph `>=1.2.11,<1.3`, Pydantic 2, existing M3A/M3B/M3C application models, SQLAlchemy async lifecycle service, pytest, deterministic scripted fakes, and PostgreSQL for the M3D persistence suite.

**Spec:** `docs/superpowers/specs/2026-08-23-verbaops-stage3-ai-provider-text-agent-design.md` plus the user-provided M3D request.

## Global Constraints

- Work single-agent only; do not use subagents or subagent-driven-development.
- Implement M3D only: no conversation HTTP endpoints, frontend, writes, mutations, RAG, embeddings, Arabic specialization, voice, HITL, approval, multi-agent behavior, streaming, or M3E work.
- Add `langgraph>=1.2.11,<1.3` and lock the exact resolved version in `uv.lock`.
- Use `StateGraph` directly with async nodes and `context_schema`; do not use `create_agent`, a top-level LangChain agent abstraction, `ToolNode`, or a LangGraph checkpointer/store.
- Keep trusted tenant, principal, customer, dependency, and service objects in immutable `AgentContext`; never put identity or credentials in mutable graph state or model-visible schemas.
- The graph exposes exactly the five M3C registry definitions and only `RiskLevel.READ_ONLY` tools.
- Hard per-turn limits are user content 8000 characters, 4 model calls, 3 tool rounds, 6 total tool calls, one validation repair, and an approximately 45-second overall deadline.
- Use graph version `text-agent-v1`, prompt version `text-agent-system-v1`, and tool schema version `commerce-read-tools-v1` on every new run.
- Do not add a migration; heads remain VerbaOps `0002_agent_runtime_v1` and Commerce `0001_create_commerce_schema`.
- Every production behavior change follows RED, expected failure, minimal GREEN, and regression verification.

---

### Task 1: Add LangGraph dependency, agent package, versions, prompt, and typed boundaries

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/verbaops/agent/__init__.py`
- Create: `src/verbaops/agent/errors.py`
- Create: `src/verbaops/agent/versions.py`
- Create: `src/verbaops/agent/context.py`
- Create: `src/verbaops/agent/state.py`
- Create: `src/verbaops/agent/prompts/__init__.py`
- Create: `src/verbaops/agent/prompts/system_v1.txt`
- Create: `tests/agent/test_boundaries.py`

**Interfaces:**
- `AgentInputError`, `AgentBusyError`, `AgentUnavailableError`, `AgentBudgetExceededError`, and `AgentProtocolError` are safe VerbaOps-owned errors with stable `error_code` values and no raw provider/tool text.
- `GRAPH_VERSION = "text-agent-v1"`, `PROMPT_VERSION = "text-agent-system-v1"`, `TOOL_SCHEMA_VERSION = "commerce-read-tools-v1"`, `MAX_USER_CONTENT_CHARS = 8000`, `MAX_MODEL_CALLS = 4`, `MAX_TOOL_ROUNDS = 3`, `MAX_TOOL_CALLS = 6`, `MAX_VALIDATION_REPAIRS = 1`, and `TURN_DEADLINE_SECONDS = 45.0` are immutable constants.
- `AgentContext` is a frozen, slotted dataclass containing `conversation_id: UUID`, `agent_run_id: UUID`, `scope: ConversationScope`, `customer_id: UUID`, `llm_client: LLMClient`, `commerce_client: CommerceClient`, `tool_registry: ToolRegistry`, and `conversation_service: ConversationService`.
- `AgentState` is a `TypedDict` containing only `messages`, `pending_tool_calls`, `last_tool_results`, `model_call_count`, `tool_round_count`, `tool_call_count`, `validation_repair_count`, `final_response`, and `failure`.
- `load_system_prompt()` reads the packaged `system_v1.txt` with `importlib.resources` and raises a safe `AgentProtocolError` if unavailable.

- [ ] **Step 1: Write failing boundary and prompt tests**

  Assert the constants, frozen context, exact state key set, safe error strings, prompt version/content requirements, and that no trusted identity or credential field appears in any M3C input schema. Add a package-build test that builds the wheel and confirms the prompt resource is present and loadable.

- [ ] **Step 2: Run the RED suite**

  Run:

  ```text
  uv run pytest tests/agent/test_boundaries.py -q
  ```

  Expected result: collection fails because `verbaops.agent` and/or `langgraph` are not yet available.

- [ ] **Step 3: Add the dependency and minimal boundaries**

  Add the exact range with uv, lock the resolved version, then create the package, safe errors, constants, immutable context, typed state, and prompt resource. The prompt must state NovaCommerce support, authoritative-tool grounding, no guessing, missing-identifier clarification, data-only tool output, immutable identity/permission boundaries, no Stage 3 mutations, safe unavailable-data behavior, and ignoring instructions embedded in tool output.

- [ ] **Step 4: Run GREEN and inspect the lock**

  Run:

  ```text
  uv run pytest tests/agent/test_boundaries.py -q
  uv lock --check
  uv run python -c "import langgraph; print(langgraph.__version__)"
  ```

  Record the exact resolved LangGraph version and verify it is within `<1.3`.

- [ ] **Step 5: Commit**

  ```text
  git add pyproject.toml uv.lock src/verbaops/agent tests/agent/test_boundaries.py
  git commit -m "feat: add read agent boundaries and prompt"
  ```

### Task 2: Build the direct StateGraph topology and model node

**Files:**
- Create: `src/verbaops/agent/graph.py`
- Create: `tests/agent/test_graph.py`
- Create: `tests/support/fake_llm.py`
- Modify: `tests/support/__init__.py` if the package requires an export

**Interfaces:**
- `build_agent_graph()` returns a compiled LangGraph graph built directly from `StateGraph(AgentState, context_schema=AgentContext)`.
- The graph contains exactly `agent`, `validate_tool_calls`, `execute_tools`, and `finalize` nodes with topology `START -> agent`, `agent -> finalize` for usable no-tool content, `agent -> validate_tool_calls` for tool calls, `validate_tool_calls -> execute_tools -> agent`, and `finalize -> END`.
- `model_node` constructs `GenerateRequest` with `CapabilityAlias.AGENT_FAST`, the versioned system prompt, at most the latest 20 user/assistant messages plus required assistant/tool loop messages, and schemas generated from the five M3C `ToolDefinition.input_model` models.
- Successful model responses append an application-owned assistant `ChatMessage`, persist `ResponseMetadata` through `ConversationService.append_model_call`, and increment `model_call_count`.
- A model response with neither non-empty content nor tool calls raises `AgentProtocolError`; LLM failures persist a failed model trace with `agent-fast` and a safe error code, then raise `AgentUnavailableError` without fabricating content.

- [ ] **Step 1: Write failing graph topology and model tests**

  Use a scripted fake LLM to assert the exact node/edge topology, five schemas in registry order, no trusted context fields in schemas, clarification content with no tool calls, bounded visible history, model-call metadata persistence, and empty-response failure.

- [ ] **Step 2: Run RED**

  ```text
  uv run pytest tests/agent/test_graph.py -q
  ```

  Expected result: import failure for `verbaops.agent.graph`.

- [ ] **Step 3: Implement the minimal graph/model node**

  Use async node functions and `Runtime[AgentContext]`/the installed LangGraph context API. Keep database writes in `ConversationService` calls inside nodes, never around the external LLM await. Use a bounded history helper that filters to roles `user` and `assistant` before selecting the latest 20 customer-visible records.

- [ ] **Step 4: Run GREEN**

  ```text
  uv run pytest tests/agent/test_graph.py -q
  ```

- [ ] **Step 5: Commit**

  ```text
  git add src/verbaops/agent/graph.py tests/agent/test_graph.py tests/support
  git commit -m "feat: build bounded read agent graph"
  ```

### Task 3: Implement explicit validation, sequential read-only tool execution, and safe failures

**Files:**
- Modify: `src/verbaops/agent/graph.py`
- Modify: `src/verbaops/agent/errors.py`
- Create: `tests/agent/test_tool_loop.py`

**Interfaces:**
- `validate_tool_calls` increments/checks the tool-round and total-call budgets, resolves names only with `ToolRegistry.get`, validates arguments with the registered Pydantic input model, and persists failed traces for unknown/malformed calls without executing them.
- One invalid/unknown round produces a compact role=`tool` schema-error result and increments `validation_repair_count`; a second invalid/unknown round raises `AgentProtocolError`/`AgentBudgetExceededError` safely.
- `execute_tools` processes valid calls strictly in emitted order, calls `ToolRegistry.execute` with `ToolExecutionContext(customer_id=context.customer_id)`, persists succeeded/failed tool traces, and appends compact JSON role=`tool` messages.
- `CommerceNotFoundError` becomes a non-enumerating `{"status":"not_found"}` tool result so the model can explain safely. Commerce timeout, unavailable, authentication, and protocol errors persist safe failure traces and terminate with `AgentUnavailableError`; no current fact is improvised.
- The graph has no dynamic imports, reflection, arbitrary callable lookup, `ToolNode`, write tool, approval state, retrieved context, or pending action state.

- [ ] **Step 1: Write failing tool-loop tests**

  Cover clarification with zero Commerce calls, one successful `get_shipment_status` loop, multiple emitted calls executing sequentially, unknown-tool non-execution, one malformed-argument repair, repeated invalid termination, 4-call model budget, 3-round budget, 6-call budget, not-found normalization, unavailable termination, and all five tool traces.

- [ ] **Step 2: Run RED**

  ```text
  uv run pytest tests/agent/test_tool_loop.py -q
  ```

  Expected result: missing node/loop behavior failures.

- [ ] **Step 3: Implement minimal validation and execution nodes**

  Use the actual M3C registry and a MockTransport-backed CommerceClient in tests. Persist each call with `risk_level="read_only"`, compact JSON arguments/results, safe status, latency, and error code. Never put tenant/principal/customer IDs or service credentials in model messages.

- [ ] **Step 4: Run GREEN**

  ```text
  uv run pytest tests/agent/test_tool_loop.py -q
  ```

- [ ] **Step 5: Commit**

  ```text
  git add src/verbaops/agent tests/agent/test_tool_loop.py
  git commit -m "feat: add bounded read-only tool loop"
  ```

### Task 4: Add AgentRuntime turn lifecycle and deadline behavior

**Files:**
- Create: `src/verbaops/agent/runtime.py`
- Modify: `src/verbaops/agent/__init__.py`
- Create: `tests/agent/test_runtime.py`

**Interfaces:**
- `AgentTurnResult` is an immutable application-owned result containing `conversation_id`, `agent_run_id`, `assistant_message_id`, `content`, and the completed `AgentRunRecord`.
- `AgentRuntime.run_turn(scope, conversation_id, customer_id, content) -> AgentTurnResult` validates content, calls `ConversationService.start_turn`, loads visible history, builds `AgentContext`, invokes the compiled graph with a conservative `recursion_limit`, and calls `complete_turn` only for usable final content.
- Busy start maps to `AgentBusyError`; all terminal typed failures call `ConversationService.fail_turn` and re-raise the safe agent error. No failure path calls `complete_turn` or creates a fabricated assistant message.
- Apply an approximately 45-second outer deadline around graph execution. Deadline expiry becomes `AgentUnavailableError`/safe timeout code after failing the run. No transaction remains open while fake LLM/Commerce calls are delayed.

- [ ] **Step 1: Write failing runtime tests**

  Assert successful clarification and tool-loop completion, two-turn operation after the first run completes, input boundaries, busy mapping, failed-run/no-assistant behavior, version propagation, slow external call transaction closure, and deadline failure.

- [ ] **Step 2: Run RED**

  ```text
  uv run pytest tests/agent/test_runtime.py -q
  ```

  Expected result: missing `AgentRuntime`/`AgentTurnResult` failures.

- [ ] **Step 3: Implement the lifecycle adapter**

  Keep the graph stateless with respect to database truth. The runtime owns only orchestration and calls the existing short-transaction `ConversationService` methods before/after external awaits.

- [ ] **Step 4: Run GREEN**

  ```text
  uv run pytest tests/agent/test_runtime.py -q
  ```

- [ ] **Step 5: Commit**

  ```text
  git add src/verbaops/agent tests/agent/test_runtime.py
  git commit -m "feat: add read agent runtime lifecycle"
  ```

### Task 5: Add real PostgreSQL M3D persistence/runtime coverage

**Files:**
- Create: `tests/agent/conftest.py`
- Create: `tests/agent/test_runtime_postgres.py`
- Modify: `pyproject.toml` marker list

**Interfaces:**
- Marker `m3d` is paired with `postgres` on the M3D integration suite.
- The suite uses the existing VerbaOps `pgvector/pgvector:0.8.6-pg16-bookworm` environment and current migrations, a real `ConversationService`, scripted fake LLM responses, and MockTransport for CommerceClient.
- Tests prove a two-turn clarification/tool flow persists user and assistant messages, running/completed agent runs, successful model metadata, tool invocation/result, graph/prompt/tool versions, and no system/tool messages in visible history.
- Tests prove failed model/tool traces persist, no fabricated assistant message is created, a completed run permits the next turn, and slow fake external work does not hold an open transaction.

- [ ] **Step 1: Write the failing PostgreSQL suite**

  Add the real engine/session fixtures and tests before changing CI. The tests should fail collection or connection when the M3D fixtures/code are absent, while remaining excluded from normal non-PostgreSQL runs.

- [ ] **Step 2: Run RED where infrastructure permits**

  ```text
  uv run pytest -m "postgres and m3d" -q
  ```

  Expected local result is an environment skip if no `NOVACOMMERCE_TEST_DATABASE_URL` exists; hosted CI must run it against the dedicated pgvector service.

- [ ] **Step 3: Implement fixtures/tests using the current schema**

  Do not add or alter an Alembic migration. Truncate only VerbaOps agent tables in fixture cleanup and use real SQLAlchemy async sessions.

- [ ] **Step 4: Run GREEN against PostgreSQL**

  ```text
  uv run alembic upgrade head
  uv run pytest -m "postgres and m3d" -q
  ```

- [ ] **Step 5: Commit**

  ```text
  git add tests/agent pyproject.toml
  git commit -m "test: add PostgreSQL read agent persistence coverage"
  ```

### Task 6: Add the focused PostgreSQL CI job and complete M3D verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_ci_contract.py`
- Modify: `Makefile` only if a dedicated `postgres-m3d` target is required by the existing conventions

**Interfaces:**
- Add independent job `postgres-m3d` using the existing pgvector PostgreSQL service, `VERBAOPS_DATABASE__URL`, `alembic upgrade head`, and `uv run pytest -m "postgres and m3d"`.
- Preserve all existing CI jobs and branch protection; do not change unrelated marker taxonomy.

- [ ] **Step 1: Write failing CI contract assertions**

  Assert the `m3d` marker, job name, pgvector image, VerbaOps migration command, exact marker selection, and preservation of existing jobs.

- [ ] **Step 2: Run RED**

  ```text
  uv run pytest tests/test_ci_contract.py -q
  ```

  Expected result: the new M3D job assertions fail because the job is absent.

- [ ] **Step 3: Add the smallest independent job**

  Copy only the established M3B PostgreSQL service setup and change the job name/marker suite to M3D. Do not make Docker or external contract jobs depend on M3D.

- [ ] **Step 4: Run the complete verification set**

  ```text
  uv lock --check
  uv sync --locked
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src tests scripts
  make check
  make commerce-contract-check
  make commerce-acceptance
  make commerce-client-contract
  make llm-gateway-contract
  make postgres-contract
  make postgres-concurrency
  make postgres-critical-race
  uv run pytest -m "postgres and m3b"
  uv run pytest -m "postgres and m3d"
  docker build --target runtime -t verbaops:m3d-local .
  git diff --check
  ```

- [ ] **Step 5: Verify locked invariants and scope**

  Confirm the OpenAPI SHA, canonical seed fingerprint, both migration heads, exact five M3C tool names and `READ_ONLY` risk, M3A contract behavior, no `src/novacommerce` production diff, no conversation HTTP routes/frontend/write/RAG/voice/Arabic/HITL/multi-agent code, no LangGraph checkpointer/store, and no `create_agent`/`ToolNode` usage.

- [ ] **Step 6: Commit, push, draft PR, and wait for hosted CI**

  Push `stage3/m3d-read-agent`, create a draft PR to `main`, wait for all hosted checks including `postgres-m3d`, keep the PR draft, do not merge, and do not begin M3E.

  ```text
  git status --short
  git push --set-upstream origin stage3/m3d-read-agent
  gh pr create --draft --base main --head stage3/m3d-read-agent
  ```

## Self-review checklist

- The plan uses only direct `StateGraph` orchestration and immutable context; there is no agent abstraction, ToolNode, checkpointer, or store.
- Every model/tool interaction is bounded, persisted through M3B short transactions, and executed only through the five M3C READ_ONLY definitions.
- The plan covers clarification, successful loop, sequential tools, one repair, all budgets, safe failures, trace persistence, history filtering, package prompt loading, PostgreSQL tests, and CI.
- No M3E API/frontend or any Stage 3 non-goal is included.
