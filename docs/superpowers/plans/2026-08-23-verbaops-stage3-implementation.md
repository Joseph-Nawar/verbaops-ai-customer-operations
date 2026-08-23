# VerbaOps AI Stage 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the M3A application-owned LLM gateway/provider layer and document executable plans for the later M3B–M3F Stage 3 increments.

**Architecture:** VerbaOps owns typed request, response, metadata, settings, and error models. `LiteLLMClient` uses only async OpenAI-compatible HTTP through `httpx` to a separately deployed LiteLLM proxy; a real proxy-to-local-provider Compose contract proves the boundary without external credentials.

**Tech Stack:** Python 3.12, Pydantic v2, `httpx`, pytest/pytest-asyncio, FastAPI local provider stub, Docker Compose, pinned LiteLLM image, uv, Ruff, mypy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-23-verbaops-stage3-ai-provider-text-agent-design.md`

## Global Constraints

- Base is exactly `6c60a557d808d7db777b3a7854573011351f28d5`.
- This branch implements M3A only; do not add M3B–M3F runtime code.
- LiteLLM is a separate Docker service and VerbaOps uses only OpenAI-compatible HTTP.
- Do not add the LiteLLM Python SDK or vendor LLM SDK imports to VerbaOps.
- Capability aliases are exactly `agent-fast`, `agent-reasoning`, `eval-judge`, and `embedding-multilingual`; only `agent-fast` is exercised.
- Provider/cost fields remain nullable unless supplied or reliably calculable; never invent metadata.
- `VERBAOPS_LLM` settings are immutable and contain `base_url`, `api_key: SecretStr`, and positive `timeout_seconds`.
- No external provider or paid credential is required at test runtime.
- Do not modify NovaCommerce production code, Commerce migrations, canonical seed data, or the Stage 2 OpenAPI snapshot.
- Every production behavior change follows RED, expected failure, minimal GREEN, regression verification, and a focused commit.

---

### Task 1: Commit the approved M3 design and complete Stage 3 plan

**Files:**
- Create: `docs/superpowers/specs/2026-08-23-verbaops-stage3-ai-provider-text-agent-design.md`
- Create: `docs/superpowers/plans/2026-08-23-verbaops-stage3-implementation.md`

- [ ] **Step 1: Validate the documents**

Run `git diff --check` and inspect that the design records the HTTP-only
boundary, aliases, metadata/error rules, secret policy, deterministic proxy
contract, M3A non-goals, and future M3B–M3F boundaries.

- [ ] **Step 2: Commit**

Run `git add docs/superpowers/specs/2026-08-23-verbaops-stage3-ai-provider-text-agent-design.md docs/superpowers/plans/2026-08-23-verbaops-stage3-implementation.md` and commit `docs: specify stage3 llm gateway architecture`.

### Task 2: Add immutable LLM settings and VerbaOps-owned request models

**Files:**
- Modify: `src/verbaops/config/settings.py`
- Modify: `src/verbaops/config/__init__.py`
- Create: `src/verbaops/llm/__init__.py`
- Create: `src/verbaops/llm/models.py`
- Modify: `pyproject.toml`
- Test: `tests/config/test_llm_settings.py`, `tests/llm/test_models.py`

**Interfaces:** `LLMSettings`; `CapabilityAlias`; `ChatMessage`;
`ToolDefinition`; `GenerateRequest`; `ResponseMetadata`; `ToolCall`;
`GenerateResponse`; and generic `StructuredResponse[T]`.

- [ ] **Step 1: Write RED tests**

Test valid `VERBAOPS_LLM__BASE_URL`, `VERBAOPS_LLM__API_KEY`, and
`VERBAOPS_LLM__TIMEOUT_SECONDS`; reject non-HTTP URLs, blank keys, non-positive
timeouts, extra fields, and mutation. Test alias values, request model
serialization to OpenAI chat-completions JSON, structured schema generation,
and nullable metadata.

- [ ] **Step 2: Run focused RED**

Run `uv run pytest tests/config/test_llm_settings.py tests/llm/test_models.py -q`.
Expect import/attribute failures because the models and settings section do
not exist yet.

- [ ] **Step 3: Implement the minimal models**

Use frozen Pydantic models with `extra="forbid"`. Serialize aliases as the
OpenAI `model` field, messages as role/content/tool-call objects, tool
definitions as function schemas, and structured responses as a strict JSON
schema response format. Keep `api_key` as `SecretStr` and never expose its
value in `repr`/`str`.

- [ ] **Step 4: Run GREEN and regression tests**

Run the focused tests, then `uv run pytest -m "not postgres and not commerce_acceptance and not llm_gateway_contract" -q`.

- [ ] **Step 5: Commit**

Commit `feat: define llm settings and application models`.

### Task 3: Add typed failures and the HTTP LiteLLM client

**Files:**
- Create: `src/verbaops/llm/errors.py`
- Create: `src/verbaops/llm/client.py`
- Create: `src/verbaops/llm/litellm.py`
- Modify: `src/verbaops/llm/__init__.py`
- Test: `tests/llm/test_litellm_client.py`

**Interfaces:** `LLMClient.generate(request) -> GenerateResponse`;
`LLMClient.generate_structured(request, response_model) -> StructuredResponse`;
`LiteLLMClient(settings, transport=None)`; and typed errors
`LLMTimeoutError`, `LLMAuthenticationError`, `LLMRateLimitError`,
`LLMUnavailableError`, and `LLMProtocolError`.

- [ ] **Step 1: Write RED transport tests**

Use deterministic `httpx.MockTransport` responses to assert exact request
serialization, plain parsing, structured Pydantic parsing, tool-call argument
parsing, usage/finish metadata, nullable cost/provider metadata, and measured
latency. Add cases for `httpx.TimeoutException`, 401/403, 429, 500/502/503,
connection failure, invalid JSON, missing choices, invalid tool arguments, and
non-object structured JSON.

- [ ] **Step 2: Run RED**

Run `uv run pytest tests/llm/test_litellm_client.py -q`; expect the new client
imports or methods to fail before implementation.

- [ ] **Step 3: Implement HTTP-only normalization**

Build the URL from the configured base URL plus `/chat/completions`, send only
OpenAI-compatible JSON and an Authorization header, use `httpx.AsyncClient`
with the configured timeout, map status/transport failures to safe typed
errors, and parse only known response fields. Include the gateway request ID
from response headers/body when available, but never include headers/body
secrets in an exception.

- [ ] **Step 4: Run GREEN and redaction proof**

Run the focused suite and a test that converts settings, client, and every
typed error to `str`/`repr` and asserts the sentinel API key is absent.

- [ ] **Step 5: Commit**

Commit `feat: add http llm gateway client`.

### Task 4: Add deterministic local provider and real LiteLLM Compose stack

**Files:**
- Create: `infra/litellm/config.yaml`
- Create: `infra/litellm/config.test.yaml`
- Create: `scripts/llm_test_provider.py`
- Create: `docker-compose.llm-gateway.yml`
- Modify: `.gitignore` only if local Compose artifacts require it
- Test: `tests/llm/test_litellm_infrastructure.py`

**Interfaces:** The stub exposes OpenAI-compatible `GET /health`,
`GET /v1/models`, and `POST /v1/chat/completions`; request markers select
deterministic plain, structured, tool-call, timeout, and failure responses.

- [ ] **Step 1: Write RED infrastructure contract tests**

Assert all four aliases are present in normal config, provider values are
environment/secrets-driven, test config routes `agent-fast` to the local stub,
the image is a stable immutable digest pin, and Compose contains only the
provider stub plus real LiteLLM service with health checks and no external-key
requirement.

- [ ] **Step 2: Run RED**

Run `uv run pytest tests/llm/test_litellm_infrastructure.py -q`; expect missing
config/stub/Compose files.

- [ ] **Step 3: Implement the stub and configs**

Use the current stable LiteLLM release `v1.98.0` pinned by its platform digest
in Compose. Keep normal provider model/base URL/key values under environment
references. Keep test values local and deterministic, with no real provider
SDK or network call.

- [ ] **Step 4: Run GREEN and Compose config validation**

Run the focused tests and `docker compose -f docker-compose.llm-gateway.yml config`.

- [ ] **Step 5: Commit**

Commit `test: add deterministic litellm gateway infrastructure`.

### Task 5: Add the permanent real-proxy contract runner and integration tests

**Files:**
- Create: `tests/integration/test_llm_gateway_contract.py`
- Create: `scripts/run_llm_gateway_contract.py`
- Modify: `Makefile`
- Modify: `pyproject.toml`
- Test: `tests/llm/test_llm_gateway_runner.py`

**Interfaces:** `llm_gateway_contract` pytest marker; `make llm-gateway-contract`;
runner functions that create a unique Compose project, select a free host
port, pass only test credentials, run the marked suite, and always tear down
volumes/networks.

- [ ] **Step 1: Write RED integration/runner tests**

Test the runner command lifecycle and cleanup in isolation. Add permanent
marked tests for plain `generate`, `generate_structured`, tool-call parsing,
and authentication/5xx failure normalization through the real proxy.

- [ ] **Step 2: Run RED**

Run `uv run pytest tests/llm/test_llm_gateway_runner.py tests/integration/test_llm_gateway_contract.py -q`; the runner/configured endpoint should fail because the stack is not implemented.

- [ ] **Step 3: Implement runner and marker exclusion**

Use a unique Compose project and ephemeral port, wait on both health checks,
run only `-m llm_gateway_contract`, propagate test status, and execute
`down --volumes --remove-orphans` in `finally`. Add the marker to pytest
configuration and exclude it from normal `make test`/quality selectors.

- [ ] **Step 4: Run GREEN through the real proxy**

Run `make llm-gateway-contract`; verify the request path is VerbaOps client →
real LiteLLM proxy → deterministic local provider and that teardown leaves no
project resources.

- [ ] **Step 5: Commit**

Commit `test: add permanent llm gateway contract`.

### Task 6: Add the independent CI job and run M3A verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md` only if the repository command documentation needs the new target
- Test: `tests/test_ci_contract.py`

- [ ] **Step 1: Write RED CI contract test**

Assert the existing job names remain present, `quality` excludes the new
contract marker where required, and an independent job named
`llm-gateway-contract` installs pinned uv/Python and invokes the Make target
without provider credentials.

- [ ] **Step 2: Implement only the new CI job**

Preserve existing jobs and branch protection. Add the independent Docker-capable
job with bounded timeout, `uv lock --check`, `uv sync --locked`, and
`make llm-gateway-contract`.

- [ ] **Step 3: Run full local verification**

Run `uv lock --check`, `uv sync --locked`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run mypy src tests scripts`, `make check`,
`make commerce-contract-check`, `make commerce-acceptance`,
`make llm-gateway-contract`, the PostgreSQL contract/concurrency/critical-race
suites, Docker runtime build, and `git diff --check`.

- [ ] **Step 4: Verify locked Stage 2 boundaries**

Compare the OpenAPI SHA, canonical seed fingerprint, Commerce migration head,
VerbaOps migration head, and `git diff --name-only` against the base. Search
VerbaOps imports for LiteLLM/vendor SDKs and LangGraph/agent/tool/conversation
code. Verify the secret-redaction tests and marker counts.

- [ ] **Step 5: Review, push, and draft PR**

Request task/whole-branch code review, address all important findings, push
`stage3/m3a-llm-gateway`, open a draft PR to `main`, wait for hosted CI, and
report the run/job statuses and PR URL. Do not mark ready, merge, or begin M3B.
