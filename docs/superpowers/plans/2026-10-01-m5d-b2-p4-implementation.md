# Implementation Plan: P4 Evidence-Linked Single Pass

**Feature:** `P4_EVIDENCE_LINKED_SINGLE_PASS` evaluation-only candidate
**Goal:** Implement the frozen P4 contract and prepare one reproducible DEV evaluation.
**Architecture:** Extend the existing `AgentEvaluationProfile` and bounded LangGraph path; issue normal `GenerateRequest`s with the existing tools plus strict JSON Schema only on eligible knowledge turns; validate claims deterministically; reuse `CitationFinalizer`; retain sanitized diagnostics in an evaluation-only run sidecar; score P4 with frozen scorer-v2 while keeping historical scoring intact.
**Tech:** Python 3.13, Pydantic, LangGraph, FastAPI, SQLAlchemy/PostgreSQL trace reads, pytest, Ruff, mypy, pre-commit, GitHub Actions.
**Sources of truth:** `docs/evaluation/stage5-m5d-b2-p4-preregistration.md`, `evals/rag/v0.2/m5d-b2-experiment-plan.json`, `evals/rag/v0.2/scorer-v2/{manifest.json,spec.json,p4-output.schema.json}`.
**Constraints:** This plan adds no runtime behavior. No provider calls, release holdout access, P4 results, `selection.json`, P0/P2/P3 reruns, scorer edits, production-default changes, retrieval/gate/model/provider/tool/budget changes, or quality-floor changes.
**Review focus:** Correct knowledge/tool mode boundary; unchanged authorization and budgets; extractive checks described as provenance rather than entailment; P4-only scorer-v2; complete separation of application, harness, freeze, scorer, and CI provenance.

## Frozen values

- Candidate `P4_EVIDENCE_LINKED_SINGLE_PASS`; prompt `text-agent-system-p4-evidence-linked-v1`; graph `text-agent-m5d-v1`; finalizer `evidence-linked-extractive-single-pass-v1`.
- Scorer `rag-v0.2-scorer-v2`; definition commit `fa800f5bfee4ee903905d89bf600642e9ddb0d95`; implementation SHA256 `aa0eff0b165a8d40e22416bad493f432931409ca70d2abee89682966c39df67a`; fixture SHA256 `7dd8662d39b14c71c01fad309341c478401d649f7165ae4ced384053b420675a`; spec SHA256 `55eb54f61be1dfe6536a23f0786021b193e032dfa0fdc760bc2caa6c5688f120`.
- Scorer manifest SHA256 `6a86c9d93f3ab9f53595d99138745311f1f4cad8e2673150be7446d1ecdd5bbb`.
- Dataset SHA256 `398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595`; knowledge manifest SHA256 `26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660`.
- Experiment plan SHA256 `2645e6430f7b936ecda089589213b2cb9828fdc4b23c526d885ff9c353617eee`; P4 schema SHA256 `c406afdf4100c01328bd86e06d8d4408c25a51a696fb00ff0ea69394ccc625e9`.
- G2 `G2_TOP_EVIDENCE_CROSS_ENCODER`, threshold `0.2554669`, profile `knowledge-retrieval-v1.1`, hybrid RRF, final five, M0 `groq/openai/gpt-oss-120b` via `agent-fast`.
- The final hosted freeze gate requires these exact 16 jobs: `quality`, `postgres-contract`, `postgres-concurrency`, `postgres-m3b`, `postgres-m3d`, `knowledge-contract`, `rag-contract`, `rag-evaluation-contract`, `m5d-evaluation-contract`, `commerce-acceptance`, `llm-gateway-contract`, `commerce-client-contract`, `agent-acceptance`, `web-quality`, `evaluation-contract`, `docker-build`.

Treat these as immutable. If scorer implementation/fixture/spec/definition or schema/plan hashes differ, stop for review; do not rebind them during implementation.

## Implementation sequence

Each task is test-first: add a focused failing regression, run it and inspect the expected failure, make the smallest change, rerun focused and adjacent regressions, review the named invariants, then commit that task. Execute one task at a time. No task begins until this amended plan has been reviewed and approved. Do not combine unrelated cleanup.

### 1. Candidate profile and prompt

**Files:** modify `src/verbaops/agent/evaluation.py`, `src/verbaops/agent/prompts/__init__.py`, `src/verbaops/evaluation/m5d_run_identity.py` only if its factory needs P4; create `src/verbaops/agent/prompts/system_p4_evidence_linked_v1.txt`; modify `tests/agent/test_m5d_grounding_candidates.py` and `tests/agent/test_prompt_package.py`.

**Interfaces:** Add the P4 enum and derive prompt (`p4-evidence-linked-v1`), graph (`text-agent-m5d-v1`), and finalizer versions from the one `AgentEvaluationProfile` passed to the app. Runtime persists prompt as `text-agent-system-{profile.prompt_version}`. The default profile/production constants remain unchanged. Prompt loader resolves the P4 resource.

**Steps:**

- [ ] Test exact P4 versions, unchanged P0/default versions, prompt loading, the distinction between retrieved knowledge and live Commerce facts, and absence of benchmark labels/aliases/expected answers. Run `uv run pytest tests/agent/test_m5d_grounding_candidates.py tests/agent/test_prompt_package.py -q`; observe failure against missing P4.
- [ ] Add only profile properties, loader mapping, and concise versioned prompt text. It must preserve untrusted-data/security language and request no routing or repair pass.
- [ ] Rerun the same command; review no default prompt changed. Commit `feat(evaluation): add P4 profile and prompt`.

### 2. Typed P4 response and frozen schema compatibility

**Files:** create `src/verbaops/agent/p4_models.py` and `tests/agent/test_p4_models.py`; read but never edit `evals/rag/v0.2/scorer-v2/p4-output.schema.json`; reuse `StructuredResponse.response_format()` from `src/verbaops/llm/models.py`.

**Interfaces:** Strict `P4Response(claims: list[P4Claim])`; each claim has only non-empty `claim_text`, `evidence_handle`, `supporting_excerpt`. Extra fields are forbidden; empty claims is valid and leads to the frozen fallback.

**Steps:**

- [ ] Add failing tests for required fields, min lengths, extra-field rejection, and generated strict schema compatibility. Run `uv run pytest tests/agent/test_p4_models.py -q` and observe missing model/failing contract.
- [ ] Add the minimal Pydantic models. Generate the OpenAI strict schema using the existing helper. Compare the complete normative schema to the committed schema. Resolve/canonicalize `$ref` paths before comparison, or use another deterministic semantic comparison that proves the full contract. In particular, compare the root claims array and its item reference/semantics, and resolve `$defs.claim` to verify object type, `additionalProperties: false`, exact required keys (`claim_text`, `evidence_handle`, `supporting_excerpt`), and string type plus `minLength: 1` for each field. Do not discard `$defs`, `definitions`, nested properties, required lists, `minLength`, types, array items, or `additionalProperties`. Only non-behavioral annotations/wrappers such as `$schema`, `$id`, generated `title`, and `description` may be ignored.
- [ ] Run `uv run pytest tests/agent/test_p4_models.py tests/evaluation/test_rag_v02_scorer_v2.py -q`; verify the frozen schema bytes are unchanged. Commit `feat(agent): model frozen P4 claims response`.

### 3. Response-format integration and Commerce tool loop

**Files:** modify `src/verbaops/agent/state.py`, `src/verbaops/agent/graph.py`; extend `tests/agent/test_m5d_grounding_candidates.py`, `tests/agent/test_tool_loop.py`.

**Interfaces:** Eligible mode predicate = P4 profile + non-empty selected `knowledge_evidence` + no tool path entered/executed. Construct the ordinary `GenerateRequest` with the existing prompt/messages, `tools=_tool_schemas(context)`, `tool_choice="auto"`, and `response_format=StructuredResponse.response_format(P4Response)`. Continue using `llm_client.generate()` so `GenerateResponse` can carry either content or tool calls. No schema when evidence is absent. After a valid Commerce tool enters existing execution, subsequent calls and terminal tool answer use the plain request path with the same P4 prompt. No extra routing or JSON conversion generation.

**Steps:**

- [ ] Add request-capture failures for knowledge mode schema+tools, no-evidence plain mode, structured-mode tool call reaches existing validator/executor without content parsing, and post-tool terminal request has no P4 schema. Pin parse ownership: `model_node` preserves response content/tool calls and does not parse; only the terminal P4 knowledge finalizer parses content after confirming there are no tool calls and no Commerce tool has executed. For active P4, blank terminal content is allowed through to that fail-closed parser; non-P4 blank-response behavior remains unchanged. Run `uv run pytest tests/agent/test_m5d_grounding_candidates.py tests/agent/test_tool_loop.py -q` and observe absent schema/mode behavior.
- [ ] Add only the required state mode/tool-path signal and predicate. Mark tool path at entry to existing valid tool execution; do not change call counters, tool names, authorization, or budget checks.
- [ ] Attach `response_format` only to eligible normal requests. If `response.tool_calls` is non-empty, bypass terminal parsing entirely and continue existing graph edges; after tool execution, plain requests resume. Do not call `generate_structured()` at this boundary.
- [ ] Rerun `uv run pytest tests/agent/test_m5d_grounding_candidates.py tests/agent/test_tool_loop.py tests/agent/test_graph.py tests/agent/test_retrieval_graph.py -q`. Review `src/verbaops/agent/versions.py` constants untouched. Commit `feat(agent): scope P4 schema to knowledge turns`.

### 4. Pure extractive validator/finalizer

**Files:** create `src/verbaops/agent/p4_grounding.py` and `tests/agent/test_p4_grounding.py`; modify `src/verbaops/agent/graph.py` only to call it; reuse `SAFE_GROUNDING_FALLBACK` and `CitationFinalizer` in `src/verbaops/retrieval/grounding.py`.

**Interfaces:** A small explicit terminal parser/helper receives response content only after the tool-call branch has been ruled out. It distinguishes (1) valid JSON and valid `P4Response`, (2) invalid JSON, (3) valid JSON with invalid P4 schema, and (4) missing/blank terminal content. Successful parse returns the typed response. For each failure it returns `parse_success=false` and one stable sanitized reason (`invalid_json`, `invalid_p4_schema`, or `missing_or_blank_terminal_content`), zero accepted claims, and the exact `SAFE_GROUNDING_FALLBACK`; it does not raise an agent protocol/budget error and never requests repair or another generation. Non-P4 parsing and failure behavior are unchanged.

After a successful parse, the pure validator receives `P4Response` and the exact selected evidence. Independently validate each claim: handle belongs to supplied evidence; non-empty excerpt is a literal, case-sensitive substring of evidence content; non-empty claim text is a literal, case-sensitive substring of the excerpt. Return ordered valid claims and stable per-claim diagnostics. Render each validated claim exactly as `<claim_text> [[<evidence_handle>]]`, in original order, joined with exactly one newline (`\n`). Add no bullets, headings, prefixes, suffixes, explanations, generated conjunctions, or punctuation. Preserve duplicate claim records if each independently validates. Pass the complete rendered string to existing `CitationFinalizer` and existing citation persistence; that finalizer remains responsible for public citation numbering and repeated-handle de-duplication. If no claims survive, use exact `SAFE_GROUNDING_FALLBACK`.

**Steps:**

- [ ] Add failing tests for all four parser states (valid JSON/schema, invalid JSON, invalid schema, missing/blank content), plus unknown handle, empty excerpt, excerpt mismatch, empty claim, claim not contained in excerpt, case mismatch, one invalid beside one valid claim, and all-rejected fallback. Assert malformed active-P4 terminal content produces parse failure, zero accepted claims, fallback, no repair, and no second model call; assert tool-call responses never invoke the parser. Run `uv run pytest tests/agent/test_p4_grounding.py tests/agent/test_m5d_grounding_candidates.py -q` and observe missing helper/behavior.
- [ ] Implement the small pure validator/render preparation; do not add an entailment model or citation subsystem.
- [ ] Add exact output tests for one claim (`claim [[K1]]`), multiple claims separated only by `\n`, repeated handle, duplicate claims preserved, and partial rejection preserving surviving order. Add a graph test for reuse of `CitationFinalizer` and existing citation persistence. Run `uv run pytest tests/agent/test_p4_grounding.py tests/agent/test_grounding_security.py tests/agent/test_m5d_grounding_candidates.py -q`.
- [ ] Review that exact substring validation is documented as source provenance, not truth/entailment. Commit `feat(agent): validate P4 extractive claims`.

### 5. Durable, evaluation-only P4 diagnostics

**Files:** create `src/verbaops/evaluation/p4_trace.py` and `tests/evaluation/test_p4_trace.py`; modify `src/verbaops/agent/state.py`, `graph.py`, `runtime.py`, `src/verbaops/api/dependencies.py`, `src/verbaops/api/lifespan.py`, `scripts/run_m5d_api.py`, and `src/verbaops/evaluation/rag_v02_grounded_runtime.py`; extend `tests/agent/test_m5d_grounding_candidates.py` and `tests/evaluation/test_rag_v02_grounded_runtime.py`.

**Trace choice:** Existing Postgres traces durably retain final assistant output, prompt/graph versions, model-call metadata, tool calls/results, and resolved citations, but not raw structured model response or per-claim rejection decisions. An in-memory trace is inaccessible to the separately running public API evaluator. A production table/migration would add durable storage solely for one evaluation candidate. Choose one narrow sidecar JSON file per actual `agent_run_id`, under the explicit canonical run directory shared by the local API and evaluation runner. Use temp-file plus atomic replace, flush/fsync, and reject missing/malformed/mismatched IDs. This is checkpoint durable without a schema migration or generic trace platform.

**Interfaces:** Whitelisted payload holds raw structured response, parse result/reason, proposed claims/handles/excerpts, handle/excerpt/claim-substring validation and rejection reasons, rendered claims, fallback state/reason, `p4_extractive_mode_active`, mode reason, `tool_path_entered`, and deactivated-after-tool. It omits credentials, headers, full prompts, unrelated history, and unrelated private data. Explicit path injection exists only for P4 evaluation; normal app startup has no sink. Runtime writes after terminal graph result; adapter reads by `agent_run_id` and embeds diagnostics/hash in the identity-bound case record.

**Steps:**

- [ ] Add failing tests for P4-only opt-in, trace keyed to one `agent_run_id`, missing/duplicate/malformed/mismatched sidecars, whitelist/sensitive data exclusion, and all required diagnostic fields. Run `uv run pytest tests/evaluation/test_p4_trace.py tests/evaluation/test_rag_v02_grounded_runtime.py -q` and observe absent sink/contract.
- [ ] Accumulate diagnostics at response parse, per-claim validation, tool transition, rendering, and fallback decisions. Avoid recording whole request messages.
- [ ] Pass a run directory explicitly from `scripts/run_m5d_api.py` through dependencies/runtime; atomically write one sidecar; read and validate it after public API completion.
- [ ] Add fake-path tests for knowledge-only, no evidence, tool emitted and terminal tool answer, malformed structured output, partial rejection, and all-claims-rejected fallback.
- [ ] Run `uv run pytest tests/evaluation/test_p4_trace.py tests/evaluation/test_rag_v02_grounded_runtime.py tests/agent/test_m5d_grounding_candidates.py tests/agent/test_tool_loop.py -q`; inspect fixture-only sidecars for privacy and path confinement. Commit `feat(evaluation): retain sanitized P4 run diagnostics`.

### 6. P4-only scorer-v2 scoring and diagnostics report

**Files:** modify `src/verbaops/evaluation/rag_grounding.py`, `src/verbaops/evaluation/rag_v02_grounded_runtime.py`, `scripts/run_m5d_grounded_eval.py`; create `tests/evaluation/test_m5d_p4_scoring.py`; extend `tests/evaluation/test_rag_grounding_runner.py` and `tests/evaluation/test_rag_v02_grounded_runtime.py`.

**Interfaces:** Use a small P4-specific assessment/scoring helper; do not change the generic `grounded_fact_score()` callback or globally replace any recognizer. For each benchmark expected fact, derive exactly `case_id::fact_id`, load that key from the audited/hash-bound frozen fixture, and assert its case, fact ID, benchmark statement, aliases, and supporting locators match that exact `RagV02Case` fact. Call `verbaops.evaluation.rag_v02_scorer_impl.classify_labeled_fact_assertion(answer, fact.aliases, positive_paraphrases=fixture_fact["positive_paraphrases"])` once and retain its `FactAssertionAssessment`. Reuse that same assessment for expected-fact coverage and the recognized grounded-fact denominator; if recognized, determine support from that fact's frozen supporting locators intersected with public cited locators, deriving supported/unsupported counts from the same assessment. Citation precision remains the existing relevance-judgment calculation. Historical P0/P1/P2/P3 scoring defaults and stored scores remain unchanged. Report exposes extractive/no-evidence/tool case counts, malformed responses, proposed/accepted claims, invalid/fabricated handles, excerpt mismatches, claim-not-substring rejections, all-rejected fallbacks, scorer-v2 nonrecognition, frozen quality metrics, and unchanged latency/cost coverage. Zero fabricated/non-supplied handles is a separate trust invariant.

**Steps:**

- [ ] Add failing tests for a P4 authored paraphrase being recognized; the same paraphrase not being added to the historical scorer; exact per-fact fixture-key and fact/statement/alias matching; one assessment reused by expected coverage, groundedness, and unsupported-recognized-fact calculation; and negated, refusal, or uncertain assessments remaining unrecognized. Add P0/P2/P3 historical-path controls. Run `uv run pytest tests/evaluation/test_m5d_p4_scoring.py tests/evaluation/test_rag_grounding_runner.py -q` and confirm the P4 paraphrase/assessment tests fail.
- [ ] Implement the P4-specific helper described above using the audited fixture map. Do not infer fixtures from alias text, key paraphrases by aliases, change `grounded_fact_score()` defaults, or rescore historical artifacts.
- [ ] Aggregate the frozen P4 diagnostics and assert zero fabricated handles independently of quality floors. Do not score incomplete runs.
- [ ] Run `uv run pytest tests/evaluation/test_m5d_p4_scoring.py tests/evaluation/test_rag_grounding_runner.py tests/evaluation/test_rag_v02_scorer_v2.py tests/evaluation/test_rag_v02_grounded_runtime.py -q`. Review that expected facts never enter model inputs and historical results remain unchanged. Commit `feat(evaluation): score P4 with frozen scorer v2`.

### 7. P4 canonical identity, inference authorization, and runner

**Files:** modify `src/verbaops/evaluation/m5d_run_identity.py`, `src/verbaops/evaluation/m5d_b2_preregistration.py`, `scripts/run_m5d_grounded_eval.py`, and (for trace path propagation from Task 5) `scripts/run_m5d_api.py`; create `tests/evaluation/test_m5d_p4_run_identity.py` and `tests/evaluation/test_m5d_b2_preregistration.py` if absent; extend `tests/evaluation/test_m5d_run_identity.py` and `tests/evaluation/test_m5d_provenance_correction.py` only where needed.

**Interfaces:** P4 run identity binds benchmark/split, dataset, knowledge manifest, experiment plan, scorer version/manifest/fixture/spec/implementation/definition commit, schema hash, separate `application_under_test_sha` and `evaluation_harness_sha`, final `freeze_commit_sha`, hosted CI run ID/head, G2/threshold, candidate/model/revision, retrieval profile, prompt/graph/finalizer versions, and stable run ID. Candidate versions derive from the same `AgentEvaluationProfile` passed to API runtime. Existing P0–P3 identity validation remains backward-compatible; P4 adds candidate-conditional required fields. Existing canonical JSON fingerprint, sidecar immutability, duplicate rejection, and resume loader remain authoritative.

Before adapter execution, require clean behavior/spec state; exact full freeze SHA; unchanged source/artifact hashes; scorer audit; 96 DEV cases only; and `require_p4_inference_authorized()` with a successful hosted run on the exact freeze head and all 16 named jobs green. The freeze is the final implementation commit, not the old preregistration/scorer-definition commit. Keep scorer definition SHA `fa800f5...` distinct. Never create holdout access or `selection.json`.

**Steps:**

- [ ] Add failing tests for missing/mismatched identity fields, app/harness/freeze separation, profile-vs-identity prompt/graph/finalizer agreement, wrong CI head, failed/missing job, altered plan/schema/scorer hashes, dirty source/spec state, and legacy P0–P3 compatibility. Run `uv run pytest tests/evaluation/test_m5d_p4_run_identity.py tests/evaluation/test_m5d_b2_preregistration.py tests/evaluation/test_m5d_run_identity.py -q` and inspect failures.
- [ ] Add a P4-specific identity builder using the audited plan, scorer manifest/schema and authoritative profile; retain existing checkpoint identity rules.
- [ ] Add only the P4 runner candidate path. Enforce `--split dev`, 96 cases, public API route, M0 contract, one canonical run, no incomplete scoring, no retries after quota, and no historical reruns.
- [ ] Call inference authorization before the first public case request. Include each P4 sidecar hash and observation/checkpoint artifact path in relative-path SHA256 references.
- [ ] Run `uv run pytest tests/evaluation/test_m5d_p4_run_identity.py tests/evaluation/test_m5d_b2_preregistration.py tests/evaluation/test_m5d_run_identity.py tests/evaluation/test_m5d_provenance_correction.py tests/evaluation/test_rag_grounding_runner.py -q`; verify no live app/provider request was made. Commit `feat(evaluation): bind canonical P4 run provenance`.

### 8. Stage 4 DEV runner support

**Files:** modify `scripts/run_m5d_stage4_dev_eval.py`; create or extend `tests/evaluation/test_m5d_stage4_dev_runner.py`; extend `tests/agent/test_m5d_grounding_candidates.py`, `tests/agent/test_tool_loop.py`, and `tests/agent/test_runtime.py`.

**Interfaces:** Stage 4 accepts P4 as an explicit candidate only on `--split dev`, with M0 and the same evaluation profile. It is run only after all RAG floors pass. Existing tool definitions, authorization, customer scoping, execution, budgets, and result scoring are untouched. Tool-involved terminal answers bypass P4 extraction; no-evidence responses stay on the plain tool/answer path.

**Steps:**

- [ ] Add failing DEV candidate allow-list and holdout rejection tests; add a Stage 4-style tool case with selected evidence proving the Commerce result uses existing tool calls/plain answer and bypasses P4 finalization.
- [ ] Add P4 only to the existing DEV comparison allow-list and profile construction.
- [ ] Assert unchanged tool schema, authorization, scoped `ToolExecutionContext`, call counters, model/tool budgets, and graph recursion limit. Do not run Stage 4 inference.
- [ ] Run `uv run pytest tests/evaluation/test_m5d_stage4_dev_runner.py tests/agent/test_m5d_grounding_candidates.py tests/agent/test_tool_loop.py tests/agent/test_runtime.py -q`. Commit `feat(evaluation): permit qualified P4 Stage 4 DEV checks`.

### 9. Final provider-free contract, verification, and implementation freeze

**Files:** finish only narrowly needed changes in `scripts/run_m5d_grounded_eval.py`, `src/verbaops/evaluation/rag_grounding.py`, `src/verbaops/evaluation/m5d_b2_preregistration.py`, tests above, and `Makefile` only if `m5d-evaluation-contract` does not already collect the P4 checks. Do not change frozen experiment or scorer artifacts.

**Steps:**

- [ ] Add end-to-end provider-free contract tests for mode states, schema compatibility, literal substring chain, CitationFinalizer reuse, Commerce invariants, sanitized trace completeness, P4-only scorer-v2, unchanged historical scorers, identity resume/rejection, DEV-only guard, and exact-head CI gate.
- [ ] Assert report diagnostic counts: extractive-mode cases; no-evidence path; tool path; malformed responses; proposed/accepted claims; invalid/fabricated handles; excerpt mismatch; claim-not-substring; all-rejected fallback; scorer-v2 nonrecognition. Keep trust invariant separate from the four floors.
- [ ] Run focused suite: `uv run pytest tests/agent/test_m5d_grounding_candidates.py tests/agent/test_prompt_package.py tests/agent/test_p4_models.py tests/agent/test_p4_grounding.py tests/agent/test_tool_loop.py tests/evaluation/test_p4_trace.py tests/evaluation/test_m5d_p4_scoring.py tests/evaluation/test_m5d_p4_run_identity.py tests/evaluation/test_m5d_stage4_dev_runner.py tests/evaluation/test_rag_v02_grounded_runtime.py tests/evaluation/test_rag_v02_scorer_v2.py -q`.
- [ ] Run `make m5d-evaluation-contract`, `make rag-evaluation-contract`, `make rag-unit-contract`, `make rag-contract`, `make knowledge-contract`, `make agent-acceptance`, `make commerce-contract-check`, `make check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pre-commit run --all-files`, and `git diff --check`. Run the provider-free evaluation contract sequence used by CI: `uv run alembic upgrade head`, `make eval-corpus-check`, `uv run pytest tests/evaluation -m "not evaluation_postgres" -q`, `uv run pytest -m "evaluation_postgres" -q` against the required test database, and `make eval-agent`. Build the runtime image with `docker build --target runtime -t verbaops:ci .`. `make commerce-contract-check` is the repository OpenAPI normalization contract.
- [ ] Run scorer audit, inspect full source diff, verify frozen hashes/plan values, confirm no P4 results, no `selection.json`, and no release-holdout reads/execution. Run no provider or Stage 4 evaluation.
- [ ] Commit the final implementation freeze only after all provider-free checks pass. This exact commit is `freeze_commit_sha`. Push it and wait for hosted CI on that exact SHA; require all 16 jobs to succeed. Bind `application_under_test_sha`, `evaluation_harness_sha`, freeze SHA, hosted CI run ID/head separately. Any later implementation/harness correction needs a new freeze SHA and fresh exact-head green CI.
- [ ] Do not start P4 inference in this plan's implementation freeze PR. Obtain a review decision first; a later authorized run uses this exact freeze evidence.

## Future inference stop conditions

There is no schema/provider compatibility probe. The eventual canonical P4 execution itself is the first provider-backed request. If Groq/LiteLLM deterministically rejects the frozen combination of JSON Schema response format, existing tools, and M0, stop and preserve the checkpoint; do not retry or redesign P4. Stop on the first explicit quota failure. Classify transient infrastructure and deterministic agent/runtime failures using the frozen plan; never score an incomplete run. Only after P4 completes 96/96, stays execution-eligible, passes every RAG floor and the zero-fabricated-handle trust invariant may Stage 4 DEV run. M5D-C remains blocked until required Stage 4 DEV, full provenance, and candidate freeze criteria pass.

## Review checklist

- [ ] Production prompt, finalizer, retrieval, model route, tool schemas, authorization, budgets, and Stage 4 authority are unchanged.
- [ ] Knowledge P4 request includes both frozen schema and current tools; tool-call responses remain tool calls; after tool execution terminal output is plain and bypasses P4 validation.
- [ ] Every rendered knowledge claim text is a literal case-sensitive substring of its excerpt, and the excerpt is a literal case-sensitive substring of its supplied evidence source; no semantic entailment claim is made.
- [ ] Existing `CitationFinalizer` persists citations; empty accepted claim set uses the exact current fallback; no repair/second pass exists.
- [ ] Diagnostics are sanitized, durable, keyed by `agent_run_id`, and sufficient to explain parse/validation/fallback/tool/scorer outcomes.
- [ ] P4 alone uses frozen scorer-v2. P0/P1/P2/P3 historical scorer and artifacts are untouched.
- [ ] App-under-test, harness, freeze commit, scorer definition, schema, and exact-head CI provenance are distinct and complete.
- [ ] Provider-free tests/checks pass and exact freeze-head hosted CI is green before any future provider inference authorization.

**Plan-only handoff:** This document is the deliverable. Do not implement its tasks until reviewed and separately authorized.
