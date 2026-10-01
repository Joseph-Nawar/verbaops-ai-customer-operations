# M5D-B2 P5 Preregistration

> **PREREGISTRATION ONLY — P5 runtime implementation and provider inference have not started.**

## P4 terminal outcome

The frozen P4 candidate `P4_EVIDENCE_LINKED_SINGLE_PASS` is closed as `P4_EXECUTION_INELIGIBLE_GROQ_RESPONSE_FORMAT_TOOL_CALLING_INCOMPATIBILITY`. Its canonical run `canonical-M0-P4-20261001T173102Z-31113cc8` contains one observation out of 96 and is incomplete and unscored. The next case received public HTTP 503 after Groq returned HTTP 400 `invalid_request_error` for `response_format`, with message `json mode cannot be combined with tool/function calling`. P4 was not resumed. Its closeout, identity, and observations remain immutable, and the P4 authorization guard continues rejecting resume and any second P4 run.

## P5 hypothesis and exact delta

P5 asks only whether the same evidence-linked extractive single-pass candidate can run when the Groq-incompatible provider-level structured-output parameter is omitted. The only intended request delta from P4 is:

| P4 knowledge request | P5 knowledge request |
| --- | --- |
| Existing `LLMClient.generate()` messages, tools, and tool choice, plus provider `response_format=json_schema` | Same messages, tools, and tool choice, with `response_format=None` |

The frozen transport value is `prompt_json_plain_content_no_response_format`. P5 requests the exact claims object through the existing P4 system prompt and parses ordinary terminal text locally. It sends no JSON mode, JSON schema, or response format to Groq. The committed P4 output schema remains the local parser/validation contract only (`schema_sent_to_provider=false`).

P5 reuses the prompt bytes at `src/verbaops/agent/prompts/system_p4_evidence_linked_v1.txt`, prompt version `text-agent-system-p4-evidence-linked-v1`, and SHA256 `29d5512332a8e0463929c44a2c46d4ff0dc8f5c6e49523db57066856278cada6`. The prompt is not copied, renamed, or edited. It contains no benchmark expected facts, aliases, case labels, or answer keys.

## Tool and no-evidence paths

The knowledge-mode predicate remains: selected knowledge evidence exists and no Commerce tool has executed in the turn. Such a request uses the normal `LLMClient.generate()` call with the existing messages, tool definitions, and tool choice; only the provider response format is absent.

Commerce tools stay available on knowledge requests. A valid tool call continues through the existing validation, authorization, customer-scoping, and execution path. Once a tool executes, the turn is tool-involved; its terminal answer follows the existing plain/tool-result path and bypasses the extractive JSON parser. No new router or generation is added. With no selected knowledge evidence, P5 uses the existing non-extractive agent/tool path and does not force a claims schema or invent evidence handles.

## Local parsing and extractive finalization

For an active no-tool terminal knowledge answer, P5 sends the ordinary text content to the existing typed `P4Response` parser and the unchanged local schema `evals/rag/v0.2/scorer-v2/p4-output.schema.json` (SHA256 `c406afdf4100c01328bd86e06d8d4408c25a51a696fb00ff0ea69394ccc625e9`). The parser distinguishes blank content, invalid JSON, schema-invalid JSON, and valid JSON. It does not strip Markdown fences, clean or repair JSON, call a model, or retry. Malformed output fails closed to the exact existing `SAFE_GROUNDING_FALLBACK`.

The existing P4 validator remains authoritative: the handle must be among supplied selected evidence; the excerpt must be a non-empty, exact, case-sensitive substring of that source; and the claim must be a non-empty, exact, case-sensitive substring of the excerpt. Valid records render in order as `<claim_text> [[<evidence_handle>]]`, joined by one newline. The existing `CitationFinalizer` handles public citation numbering. If no valid claims remain, use the same safe fallback. No entailment model or repair pass is added.

## Frozen evaluation inputs

P5 experiment plan SHA256: `62270ba5de74cd24a0c0f8b39988f6f8563106fae640b97aa7ccc5198255176a`. The machine-readable contract is [m5d-b2-p5-experiment-plan.json](../../evals/rag/v0.2/m5d-b2-p5-experiment-plan.json).

- Candidate: `P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS`, preregistered and not implemented.
- Split and size: DEV only, all 96 rag-v0.2 cases, one canonical run.
- Dataset SHA256: `398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595`.
- Knowledge-manifest SHA256: `26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660`.
- Retrieval: `knowledge-retrieval-v1.1`, `hybrid_rrf`, final five evidence items.
- Gate: `G2_TOP_EVIDENCE_CROSS_ENCODER`, threshold `0.2554669`.
- Model: M0 `groq/openai/gpt-oss-120b` through `agent-fast`.
- Graph: `text-agent-m5d-v1`.
- Finalizer: `evidence-linked-extractive-single-pass-v1`.
- Scorer: frozen `rag-v0.2-scorer-v2`, definition commit `fa800f5bfee4ee903905d89bf600642e9ddb0d95`; implementation `aa0eff0b165a8d40e22416bad493f432931409ca70d2abee89682966c39df67a`; fixtures `7dd8662d39b14c71c01fad309341c478401d649f7165ae4ced384053b420675a`; spec `55eb54f61be1dfe6536a23f0786021b193e032dfa0fdc760bc2caa6c5688f120`; manifest `6a86c9d93f3ab9f53595d99138745311f1f4cad8e2673150be7446d1ecdd5bbb`.

P5 does not rerun P0-P4, access the release holdout, create `selection.json`, or change any historical scores. It does not change production defaults, retrieval, tools, authorization, customer scoping, model/provider, prompt, or runtime budgets.

## Canonical identity and evidence

The P5 run identity must include the exact committed P5 plan SHA256 and the field `knowledge_terminal_output_transport=prompt_json_plain_content_no_response_format`, independently of the candidate ID. It also binds dataset and knowledge hashes; scorer definition, implementation, manifest, fixture, and spec; local output-schema hash; application-under-test SHA; evaluation-harness SHA; implementation-freeze SHA; exact-head hosted CI run/head/conclusion and required-job-conclusions hash; gate/threshold; candidate/model/provider/capability; retrieval profile/strategy/evidence count; prompt path/version/hash; graph/finalizer versions; and the unique run ID `canonical-M0-P5-<UTC timestamp>-<8 lowercase hex chars>`.

P5 sidecars use the existing narrow, path-confined evaluation-only storage approach, but identify the candidate and payload as P5. Each case records whether knowledge mode was active, the transport value, `provider_response_format_attached=false`, tool-path entry/deactivation, raw terminal content when parsing applies, parse and schema outcomes, proposed claims/handles/excerpts, per-claim handle/excerpt results and rejection reasons, rendered claims, and fallback. Non-applicable structured fields are represented consistently without fabricating output. Credentials, headers, full prompts, and unrelated private data are excluded.

## Quality, budgets, and stop rules

All quality floors remain unchanged: citation precision at least 0.95 with a nonzero denominator; labeled groundedness at least 0.90 with a nonzero denominator; unsupported recognized-fact rate at most 0.10; expected-fact coverage at least 0.70; and zero fabricated or non-supplied evidence handles.

The run has 96 public case requests and a hard ceiling of four model calls per case (384 total, not a promised count), with the existing limits of three tool rounds, six tool calls, graph recursion limit 20, and 45-second turn deadline. P5 adds no repair generation. The first provider-backed P5 request is the canonical public-application DEV run after implementation freeze and exact-head green hosted CI; no smoke, diagnostic, or compatibility probe is permitted. At the first explicit provider quota or protocol incompatibility, stop and preserve evidence. Do not retry a failed case, substitute model/provider, or change the candidate mid-run. A transient infrastructure interruption is classified before resuming the same identity. Incomplete runs are not scored.

Stage 4 DEV may be considered only after P5 completes 96/96, remains execution-eligible, and passes every RAG floor plus the zero-fabricated-handle invariant. M5D-C remains blocked until those conditions, the required Stage 4 DEV regression, and complete provenance are satisfied. Release holdout remains sealed until a later separately reviewed milestone.

## Alternatives rejected

- **Remove tools from knowledge requests:** changes tool availability and routing instead of isolating the incompatible request parameter.
- **Two-pass generation:** adds calls, cost, and latency and abandons the single-pass hypothesis.
- **Provider/model switch:** confounds the transport delta with a different model or provider.
- **JSON repair generation:** adds adaptive behavior and another model call.
- **Heuristic JSON repair:** hides plain prompt adherence failures instead of measuring them under the frozen parser.

## Provider-free implementation contract

Before any future P5 inference, tests must prove: P5 knowledge requests retain existing tools while using `response_format=None`; P4 still attaches its frozen response format in historical/provider-free coverage; tool calls enter the existing loop; post-tool answers bypass extractive parsing; P5 terminal knowledge content enters the unchanged parser; malformed JSON fails closed without another model call; valid JSON uses unchanged validation/finalization; scorer-v2 is unchanged; P4 closeout remains auditable and P4 resume/second-run authorization remains blocked; and the P5 plan plus run identity bind the new transport mode. The implementation freeze must pass the full provider-free suite and fresh exact-head hosted CI before the canonical P5 run.
