# VerbaOps AI Stage 3 Source of Truth

## Purpose

Stage 3 is delivered through six bounded milestones. Each milestone is planned
from the then-current merged repository; later milestone details must not be
invented prematurely.

M3A–M3F are complete on the merged Stage 3 line. The Stage 3 read-only path
is now locked; follow-up work must be planned as a later stage.

## Exact Stage 3 milestones

### M3A — LLM Gateway & Provider Layer

Establish the application-owned, HTTP-only LLM gateway boundary through a
separate, pinned LiteLLM proxy. Deliver typed request/response models, safe
metadata and errors, immutable settings, deterministic provider-free contract
testing, and the reusable HTTP client lifecycle needed by future application
lifespan ownership.

Exit criteria: plain and structured generation work through a real LiteLLM
proxy; tool calls and metadata normalize safely; gateway failures become typed
errors; secrets cannot leak; no provider SDK or paid credential is required;
the permanent contract and all Stage 1/2 gates remain green.

### M3B — Conversation & Trace Persistence

Define and implement the approved conversation, turn, message, and trace
persistence boundary, including its lifecycle and observability contract.

Exit criteria: the approved persistence schema and migrations are tested from
the then-current repository, trace ownership is explicit, and persistence
acceptance is green without changing the M3A provider boundary.

### M3C — NovaCommerce Read Client & Typed Tool Registry

Add the application-owned NovaCommerce read client and typed registry for
approved read-only tools.

Exit criteria: read contracts are generated or validated from the locked
NovaCommerce API, tool schemas and errors are typed, and no write or mutation
operation is exposed.

### M3D — First LangGraph Read-Only Agent Runtime

Add the first text-only, read-only LangGraph runtime using the M3A gateway and
M3C read-only tool registry.

Exit criteria: one bounded read-only agent turn is deterministic and tested,
tool access is allowlisted, and no writes, multi-agent architecture, HITL, or
approval flow is introduced.

### M3E — Conversation API & End-to-End Agent Acceptance

Expose the approved conversation API and prove the persisted, read-only agent
flow end to end.

Exit criteria: API, persistence, gateway, agent, and read-only Commerce paths
have an acceptance suite with safe failure behavior and no mutation surface.

### M3F — Minimal Next.js Web Chat & Stage 3 Lock

Add the minimal Next.js text chat client and lock the complete Stage 3 path.

Exit criteria: the web chat completes the approved text-only read-only flow,
security and regression gates are green, and Stage 3 is explicitly locked for
follow-up work.

## M3A locked architecture

LiteLLM runs as a separate Docker service. VerbaOps communicates with it only
through OpenAI-compatible HTTP using `httpx`; neither the LiteLLM Python SDK
nor any vendor LLM SDK is permitted in application code. The application owns
the request, response, metadata, settings, and error models in:

- `src/verbaops/llm/client.py`
- `src/verbaops/llm/models.py`
- `src/verbaops/llm/errors.py`
- `src/verbaops/llm/litellm.py`

`LLMClient` exposes asynchronous `generate()` and `generate_structured()`.
Callers work only with VerbaOps-owned models and exactly these capability
aliases: `agent-fast`, `agent-reasoning`, `eval-judge`, and
`embedding-multilingual`. M3A exercises only `agent-fast`.

`ResponseMetadata` preserves these distinct nullable concepts:

- `capability_alias`
- `gateway_request_id`
- `gateway_model_id`
- `model`
- `provider`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `latency_ms`
- `cost_usd`
- `finish_reason`

The adapter never invents unavailable metadata. Gateway/provider failures are
typed VerbaOps errors. Structured content that cannot be parsed or validated
against its requested Pydantic model is an `LLMStructuredOutputError`;
malformed gateway envelopes, protocol payloads, and tool calls remain
`LLMProtocolError`. Credentials are never included in logs, representations,
exception messages, or response metadata.

The caller injects and owns a reusable `httpx.AsyncClient`; `LiteLLMClient`
never creates or closes that client. The future FastAPI lifespan owns the
production client lifecycle.

VerbaOps configuration has an immutable `VERBAOPS_LLM` section with `base_url`,
`api_key` as `SecretStr`, and positive `timeout_seconds`. Runtime `httpx` is a
production dependency.

## LiteLLM infrastructure and testing

The deployment image is stable and immutably pinned to LiteLLM `v1.98.0`.
Normal configuration receives provider model, base URL, keys, and proxy
secrets through environment/secrets. Test configuration routes `agent-fast`
through a deterministic local OpenAI-compatible provider stub. The permanent
contract is:

`VerbaOps LiteLLMClient → real LiteLLM Proxy → deterministic local provider stub`

It requires no external provider call or paid credential.

Unit tests cover settings, serialization, plain and structured parsing,
tool-call parsing, metadata, nullable provider/cost fields, transport/status
failures, malformed protocol responses, structured-output failures, reusable
client ownership, and secret redaction. The dedicated `llm_gateway_contract`
marker and `make llm-gateway-contract` target run the real proxy contract.

## Explicit Stage 3 non-goals

Stage 3 explicitly does not implement:

- write tools;
- cancellation, reschedule, return, or ticket mutations;
- RAG;
- embeddings or vector search;
- Arabic specialization;
- voice;
- multi-agent architecture;
- HITL or approval;
- streaming UI.

M3F adds only the minimal browser chat and server-only BFF over the M3E API.
Stage 3 does not implement writes, RAG, voice, Arabic specialization, HITL,
multi-agent behavior, streaming, or a production identity provider. It does
not modify NovaCommerce production code, Commerce migrations, the Stage 2
OpenAPI contract, or the canonical seed.
