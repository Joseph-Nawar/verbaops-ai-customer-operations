# NovaCommerce Read Client & Typed Tool Registry Implementation Plan

> **For agentic workers:** Execute inline in this session with strict RED-GREEN TDD. Single-agent execution is required; do not use subagents or subagent-driven-development.

**Goal:** Add an application-owned authenticated HTTP read client for NovaCommerce and an explicit, immutable registry exposing exactly five typed READ_ONLY tools for M3D.

**Architecture:** `CommerceClient` owns no HTTP lifecycle and consumes an injected reusable `httpx.AsyncClient`. It maps the locked NovaCommerce OpenAPI read responses into VerbaOps-owned Pydantic models and normalizes transport/status/protocol failures into safe typed errors. A separate explicit tool registry binds five validated input models, five concise output models, trusted server-side execution context, retry metadata, and concrete handlers; model-visible schemas never contain identity or credential fields.

**Tech Stack:** Python 3.12, Pydantic 2, pydantic-settings, SQLAlchemy-era project conventions, httpx, pytest/httpx.MockTransport, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-23-verbaops-stage3-ai-provider-text-agent-design.md` plus the attached M3C request and locked `contracts/novacommerce-openapi.json`.

## Global Constraints

- Work single-agent only; do not use subagents or subagent-driven-development.
- Implement M3C only: no LangGraph, agent runtime, conversation API, frontend, writes, mutations, RAG, embeddings, Arabic specialization, voice, HITL, approvals, or multi-agent behavior.
- The only production boundary is `src/verbaops` -> application-owned `CommerceClient` -> authenticated NovaCommerce HTTP API.
- `src/verbaops` must contain zero Python imports from `novacommerce`.
- Use an injected reusable `httpx.AsyncClient`; `CommerceClient` must not create or close it.
- Service credentials are `SecretStr` and must not appear in reprs, logs, or errors.
- Retry exactly once only for timeout, connection/transport failure, and HTTP 502/503/504; maximum two attempts with no sleep/backoff.
- The five model-visible tools are exactly `get_order_status`, `get_shipment_status`, `get_refund_status`, `search_products`, and `list_delivery_slots`, all `READ_ONLY`.
- No VerbaOps or Commerce migration changes; heads remain `0002_agent_runtime_v1` and `0001_create_commerce_schema`.
- Preserve the locked OpenAPI SHA and canonical seed fingerprint.
- Every production behavior change follows RED, expected failure, minimal GREEN, and regression verification.

---

### Task 1: Establish M3C settings and response/error RED suite

**Files:**
- Create: `tests/config/test_commerce_settings.py`
- Create: `tests/commerce/__init__.py`
- Create: `tests/commerce/test_models.py`
- Create: `tests/commerce/test_errors.py`
- Modify: `src/verbaops/config/settings.py` only after the RED tests fail
- Modify: `src/verbaops/config/__init__.py` only after the RED tests fail

**Interfaces:**
- Produce immutable `CommerceSettings` with `base_url`, `service_token: SecretStr`, and positive `timeout_seconds`, nested under `Settings.commerce` and loaded from `VERBAOPS_COMMERCE__...`.
- Produce VerbaOps-owned response models matching the locked schemas for order, order item, shipment, refund, product search/product, and delivery slot, preserving monetary strings exactly.
- Produce `CommerceError`, `CommerceAuthenticationError`, `CommerceNotFoundError`, `CommerceTimeoutError`, `CommerceUnavailableError`, and `CommerceProtocolError` with secret-safe strings and reprs.

- [ ] **Step 1: Write failing settings tests**

  Cover valid nested environment loading, absolute HTTP(S) URL validation, URL credentials/query/fragment rejection without echoing secrets, blank token rejection, positive timeout validation, frozen mutation rejection, extra-field rejection, and repr/error redaction.

- [ ] **Step 2: Write failing model/error tests**

  Validate representative OpenAPI payloads, enum values, UUID/date/datetime/time parsing, `additionalProperties` rejection, and exact preservation of decimal strings. Assert every typed error omits bearer tokens, raw response bodies, and credential-bearing URLs.

- [ ] **Step 3: Run the focused RED suite**

  Run: `uv run pytest tests/config/test_commerce_settings.py tests/commerce/test_models.py tests/commerce/test_errors.py -q`

  Expected: collection or import failures because the new settings/models/errors do not exist.

- [ ] **Step 4: Implement the minimal settings/models/errors**

  Follow the existing `LLMSettings` sanitization and `SecretStr` patterns. Keep response models application-owned and limited to fields in the locked OpenAPI schemas; do not import NovaCommerce modules.

- [ ] **Step 5: Run the focused GREEN suite and commit**

  Run the same focused command; expected result is all tests passing. Commit with `feat: add commerce settings models and errors`.

### Task 2: Implement the authenticated CommerceClient with bounded retries

**Files:**
- Create: `src/verbaops/commerce/__init__.py`
- Create: `src/verbaops/commerce/client.py`
- Create: `tests/commerce/test_client.py`

**Interfaces:**
- `CommerceClient(settings: CommerceSettings, http_client: httpx.AsyncClient)` owns neither construction nor closure of `http_client`.
- Customer-scoped methods accept `order_id: UUID` and trusted `customer_id: UUID`.
- Product and delivery-slot methods accept only their typed read arguments and never send a customer header.
- Methods return VerbaOps-owned models: `get_order`, `get_shipment`, `get_refunds`, `search_products`, and `list_delivery_slots`.

- [ ] **Step 1: Write MockTransport RED tests**

  Assert exact paths/query names from the locked contract, `Authorization: Bearer ...`, customer header only on order/shipment/refund calls, response parsing, decimal preservation, injected-client reuse across sequential calls, and caller-owned client lifecycle.

- [ ] **Step 2: Write failure and retry RED tests**

  Parameterize 401/403, 404, 429, unexpected 4xx, invalid JSON/schema, timeout, connection failure, and 502/503/504 mappings. Assert retryable failures make exactly two total attempts, non-retryable failures make one, successful responses make one, and no safe error string contains secrets or raw backend text.

- [ ] **Step 3: Run the client RED suite**

  Run: `uv run pytest tests/commerce/test_client.py -q`

  Expected: import/attribute failures because the client is not implemented.

- [ ] **Step 4: Implement the minimal client**

  Build only fixed endpoint methods and a small explicit request loop. Attach fixed headers internally, parse JSON with Pydantic, map status/transport failures to typed errors, retry once for the four specified transient classes, and never expose raw `httpx.Response` values.

- [ ] **Step 5: Run GREEN and commit**

  Run the focused client suite and commit with `feat: add authenticated commerce read client`.

### Task 3: Define typed read-only tool inputs, outputs, context, handlers, and registry

**Files:**
- Create: `src/verbaops/tools/__init__.py`
- Create: `src/verbaops/tools/models.py`
- Create: `src/verbaops/tools/commerce_reads.py`
- Create: `src/verbaops/tools/registry.py`
- Create: `tests/tools/test_models.py`
- Create: `tests/tools/test_commerce_reads.py`
- Create: `tests/tools/test_registry.py`
- Create: `tests/architecture/test_m3c_isolation.py`

**Interfaces:**
- Frozen, `extra="forbid"` input models: `GetOrderStatusInput`, `GetShipmentStatusInput`, `GetRefundStatusInput`, `SearchProductsInput`, and `ListDeliverySlotsInput`.
- Frozen server-side `ToolExecutionContext` contains only trusted data required by handlers, currently `customer_id: UUID`.
- Frozen typed output models contain only concise support-relevant fields grounded in the OpenAPI response models.
- `RiskLevel.READ_ONLY`, `RetryPolicy` with the fixed two-attempt read policy, and immutable `ToolDefinition` fields: name, description, input model, output model, risk level, timeout seconds, retry policy, handler.
- Explicit `ToolRegistry` rejects duplicate definitions, rejects unknown lookup deterministically, and exposes exactly the five production names.
- Handlers receive validated input, trusted execution context, and `CommerceClient`; customer IDs come only from context.

- [ ] **Step 1: Write failing registry/input/handler tests**

  Assert exact five names and READ_ONLY risk, duplicate/unknown failures, strict schemas, nonblank bounded product query, limit 1..10, date ordering and bounded delivery range, no identity fields or credentials in JSON schemas, trusted customer forwarding, normalized outputs, and no write/mutation names.

- [ ] **Step 2: Run the tool RED suite**

  Run: `uv run pytest tests/tools tests/architecture/test_m3c_isolation.py -q`

  Expected: import/attribute failures because the tool package is absent.

- [ ] **Step 3: Implement the minimal explicit registry and handlers**

  Bind the five handlers in a literal allowlist. Do not use reflection or arbitrary callable registration in the production registry. Keep context separate from model-visible input and enforce output normalization through Pydantic models.

- [ ] **Step 4: Run GREEN and commit**

  Run the focused tool suite and commit with `feat: add allowlisted commerce read tools`.

### Task 4: Add the permanent real NovaCommerce client contract

**Files:**
- Create: `tests/integration/test_commerce_client_contract.py`
- Create or modify: `scripts/run_commerce_client_contract.py`
- Modify: `Makefile`
- Modify: `pyproject.toml` marker configuration

**Interfaces:**
- Marker: `commerce_client_contract`.
- Target: `make commerce-client-contract`.
- Runner reuses disposable Compose/seed patterns without changing locked Stage 2 acceptance tests or fixtures.

- [ ] **Step 1: Write the contract test/runner RED test**

  Define a small runner contract that starts disposable NovaCommerce infrastructure, authenticates with a generated local service token, seeds canonical data, then exercises known owned order, shipment, refunds, product search, delivery slots, foreign/nonexistent order normalization, invalid auth normalization, and confirms only GET methods are used.

- [ ] **Step 2: Run the contract RED check**

  Run: `make commerce-client-contract`

  Expected: missing target/runner or collection failure.

- [ ] **Step 3: Implement the isolated contract runner and marker**

  Reuse existing acceptance lifecycle helpers where possible. Keep the suite separate from `commerce_acceptance`; never alter Stage 2 acceptance markers or production Commerce code.

- [ ] **Step 4: Run GREEN and commit**

  Run: `make commerce-client-contract`; record the exact passing test count and commit with `test: add real commerce client contract`.

### Task 5: Wire CI and complete M3C verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_ci_contract.py`
- Modify: any focused M3C tests required by verified failures only

- [ ] **Step 1: Write failing CI contract assertions**

  Assert the new independent `commerce-client-contract` job, its marker exclusion from normal tests, preservation of all existing jobs, and the exact Make target.

- [ ] **Step 2: Implement the smallest CI change**

  Add only the independent job and normal-suite exclusion. Do not alter PostgreSQL marker taxonomy or branch protection.

- [ ] **Step 3: Run all local verification**

  Run fresh:

  ```text
  uv lock --check
  uv sync --locked
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src tests scripts
  make check
  make commerce-contract-check
  make commerce-acceptance
  make llm-gateway-contract
  make commerce-client-contract
  all feasible PostgreSQL suites
  docker build --target runtime -t verbaops:m3c-local .
  git diff --check
  ```

- [ ] **Step 4: Verify locked invariants and scope**

  Confirm OpenAPI SHA `4EC1D8CDB34C797F45015EE0074DF1BF7D376DC866E7E3FF43EE7D43902A9F9E`, seed fingerprint `f9c5a32603d7087eb820deffcbf8fdd27324e0fbd677d3f9c4774b335aadacdb`, both migration heads, M3A/M3B gates, empty `src/novacommerce` production diff, zero `novacommerce` imports under `src/verbaops`, and absence of LangGraph/agent/API/frontend/write/RAG/voice/HITL/multi-agent scope.

- [ ] **Step 5: Commit, push, open draft PR, and wait for hosted CI**

  Push `stage3/m3c-commerce-read-tools`, open a DRAFT PR to `main`, verify the hosted `commerce-client-contract` and all existing jobs are green, keep the PR draft, and do not merge or begin M3D.

## Self-review checklist

- The plan covers settings, all five HTTP reads, safe typed failures, exact retry behavior, reusable client ownership, response preservation, five-tool allowlisting, trusted customer handling, contract testing, CI, and every requested verification gate.
- No task adds a migration, imports NovaCommerce Python code into VerbaOps, or introduces an agent runtime or mutation operation.
- The only future-facing dependency is the explicit handler/registry interface M3D will consume; no LangGraph code or API surface is planned here.
