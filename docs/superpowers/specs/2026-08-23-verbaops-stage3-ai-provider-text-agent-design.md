# VerbaOps AI Stage 3 M3A–M3F Provider/Text-Agent Design

## Purpose

Stage 3 adds the AI execution boundary in six deliberately separated increments.
M3A, the only increment implemented by this branch, establishes an
application-owned LLM gateway client and a real LiteLLM proxy boundary. Later
increments consume that boundary but are not part of this change.

## Locked M3A architecture

LiteLLM runs as a separate Docker service. VerbaOps communicates with it only
through OpenAI-compatible HTTP using `httpx`; neither the LiteLLM Python SDK
nor any vendor LLM SDK is permitted in application code. The application owns
the request, response, metadata, settings, and error models in:

- `src/verbaops/llm/client.py`
- `src/verbaops/llm/models.py`
- `src/verbaops/llm/errors.py`
- `src/verbaops/llm/litellm.py`

`LLMClient` exposes asynchronous `generate()` and `generate_structured()`.
Callers work only with VerbaOps-owned models and capability aliases:
`agent-fast`, `agent-reasoning`, `eval-judge`, and
`embedding-multilingual`. Stage 3 M3A exercises only `agent-fast`.

The gateway adapter normalizes, without inventing unavailable values, the
capability alias, gateway request ID, gateway model ID/model, input/output
tokens, latency, cost when supplied or reliably calculable, finish reason,
content, and tool calls. Gateway/provider failures become typed VerbaOps
errors. Credentials are never included in logs, representations, exception
messages, or response metadata.

VerbaOps configuration has an immutable `VERBAOPS_LLM` section with
`base_url`, `api_key` as `SecretStr`, and positive `timeout_seconds`. Runtime
`httpx` is a production dependency.

## LiteLLM infrastructure

`infra/litellm/config.yaml` is the deployment configuration. It maps all four
capability aliases and receives provider model names, base URLs, API keys, and
the proxy master key from environment/secrets. The image is a stable,
immutable LiteLLM release pin, never `latest`, RC, or dev.

`infra/litellm/config.test.yaml` maps `agent-fast` to a deterministic local
OpenAI-compatible provider stub. A dedicated Compose stack starts the stub and
the real LiteLLM proxy; it never contacts an external provider and requires no
paid credential.

## VerbaOps-owned model contract

Requests contain an alias, ordered chat messages, optional generation controls,
and optional OpenAI-shaped tool definitions represented by VerbaOps models.
Plain responses expose text and normalized metadata. Structured responses parse
the JSON content into a caller-supplied Pydantic model while retaining the same
metadata and tool calls. Tool-call arguments are parsed from the gateway's JSON
string into a JSON object when valid; malformed gateway payloads are protocol
errors rather than silently invented calls.

Metadata fields are nullable where LiteLLM/provider responses may omit them.
Latency is measured by the application adapter. Cost is retained only when the
gateway supplies it or it is reliably calculable from complete usage data; the
adapter does not estimate it from incomplete information.

## Failure contract

The adapter distinguishes timeout, authentication/authorization, rate-limit,
gateway unavailable/5xx, and malformed/protocol responses. Error text contains
status/category and safe diagnostic context only. It never contains an API key,
Authorization header, URL credentials, raw provider body, or serialized secret
settings.

## Testing and CI

Unit tests use deterministic `httpx` transports to cover settings validation,
serialization, plain and structured parsing, tool calls, metadata, nullable
provider/cost fields, timeout, auth, rate limits, 5xx/unavailable,
malformed/protocol payloads, and secret redaction.

A permanent `llm_gateway_contract` pytest marker runs through a real LiteLLM
Proxy and the deterministic local provider stub. It covers plain generation,
structured generation, tool-call parsing, and failure normalization. The
`llm-gateway-contract` Make target owns the disposable Compose lifecycle.
Ordinary unit/quality selectors exclude this marker; the independent CI job
named `llm-gateway-contract` runs it without external provider credentials.

## Explicit non-goals for M3A

This branch does not implement M3B–M3F, LangGraph, agent or conversation
runtime, tool execution, Commerce client integration, persistence, frontend,
RAG, writes, Arabic specialization, or voice. It does not modify NovaCommerce
production code, Commerce migrations, the Stage 2 OpenAPI contract, or the
canonical seed.

## Future Stage 3 increments

- **M3B — text-agent runtime:** compose a text-only agent runtime over the M3A
  client, with explicit turn boundaries and no persistence.
- **M3C — conversation state:** add the approved conversation persistence model
  and lifecycle, keeping provider calls behind `LLMClient`.
- **M3D — Commerce tools:** add typed read/write tool contracts and the
  application-owned Commerce client only after the tool boundary is approved.
- **M3E — retrieval and Arabic specialization:** add RAG, language policy,
  prompt/evaluation assets, and Arabic-specific behavior behind measured
  interfaces.
- **M3F — voice and end-to-end acceptance:** add voice adapters and the final
  end-to-end acceptance path without weakening the M3A gateway contract.
