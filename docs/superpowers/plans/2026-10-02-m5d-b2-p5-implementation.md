# P5 Prompt JSON Extractive Single-Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans`. Implement task by task with test-driven development; each task ends with its own commit. This plan must be reviewed and approved before any task begins.

**Goal:** Add the preregistered, evaluation-only `P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS` as a minimal P4 extension that omits provider-level `response_format` from knowledge requests.

**Frozen sources:** [P5 plan](evals/rag/v0.2/m5d-b2-p5-experiment-plan.json), [P5 preregistration](docs/evaluation/stage5-m5d-b2-p5-preregistration.md), the P4 plan, and its closed canonical run. P5 plan SHA256: `e700ec31f157f47837489fc2d26e1296388405f447701286adc899d7b42fc20e`.

## Design constraints

- Reuse prompt file/version `src/verbaops/agent/prompts/system_p4_evidence_linked_v1.txt` / `text-agent-system-p4-evidence-linked-v1`, graph `text-agent-m5d-v1`, finalizer `evidence-linked-extractive-single-pass-v1`, `P4Response`, its parser/validator/renderer, `CitationFinalizer`, and scorer-v2. Keep P4 behavior, evidence, closeout, and historical scoring unchanged.
- Inspect actual `GenerateRequest`s. P4 remains `tools + tool_choice="auto" + response_format=<P4 schema>`; P5 is `same tools + tool_choice="auto" + response_format=None`. This is the only request-level delta. Do not use a new client, parser, router, repair, or generation pass.
- Preserve the P4 predicate exactly: P5 knowledge/extractive mode requires selected evidence and existing `tool_path_entered=false`. A valid Commerce call entering execution sets that state even when its authoritative business result is `not_found`; subsequent terminal output bypasses extractive parsing. An invalid call that never executes does not set it. Keep existing tool-loop behavior and state; add no P5 routing state.
- P5 durable evidence must be P5-labelled and use the frozen P5 trace fields, transport value `prompt_json_plain_content_no_response_format`, and `provider_response_format_attached=false`. Runtime trace code uses narrow code constants; it must not read or require the P5 experiment-plan file in the application image. Repository tests compare those constants with the committed plan. Prefer a narrow P5 projection/store over renaming P4 tracing.
- Keep G2/`0.2554669`, retrieval, model/provider, budgets, scorer, schema, data, and quality floors frozen. P5 has its own plan/identity/authorization and `canonical-M0-P5-...` namespace; P4 remains closed. DEV only, 96 cases, no baseline reruns, holdout, `selection.json`, Stage 4, or M5D-C in implementation.
- Before later P5 inference, require a clean committed implementation freeze, exact-head green hosted CI (all 16 jobs), and passing provider-free verification with all frozen P5/P4 hashes unchanged.

## Tasks

### 1. Candidate profile and explicit request transport

**Files:** `src/verbaops/agent/evaluation.py`, `src/verbaops/agent/graph.py`, `tests/agent/test_m5d_grounding_candidates.py`.

- **RED:** Add tests for the P5 profile reusing P4 versions and for captured `GenerateRequest`s: both candidates retain identical tools and `tool_choice="auto"`; only P4 has a response format. Run `uv run pytest tests/agent/test_m5d_grounding_candidates.py -k 'p5_profile or p4_p5_knowledge_generate_requests' -q` and confirm failure.
- Add the P5 evaluation profile and an explicit candidate check that omits `response_format` only for P5. Keep the `LLMClient.generate()` boundary and production defaults unchanged.
- **GREEN:** Run the focused tests and full candidate test module; commit `feat(agent): add P5 evaluation request profile`.

### 2. Reuse terminal parsing, extractive finalization, and tool loop

**Files:** `src/verbaops/agent/graph.py`; focused tests in `tests/agent/test_m5d_grounding_candidates.py`, `tests/agent/test_tool_loop.py`, and `tests/agent/test_p4_grounding.py`.

- **RED:** Test ordinary P5 JSON reaches the existing parser/finalizer; malformed JSON returns exact `SAFE_GROUNDING_FALLBACK` with no extra model call; (1) a valid Commerce call with a successful result sets `tool_path_entered=true` and the later terminal answer bypasses parsing; (2) a valid call returning authoritative `not_found` does the same; and (3) an invalid call that never executes does not set the state and preserves existing validation-repair/budget behavior.
- Extend the existing P4 knowledge finalization branch to P5 without attaching P4's provider schema. Keep no-evidence behavior, tool validation/authorization, budgets, exact extractive checks/rendering, and citation finalization unchanged.
- **GREEN:** Run `uv run pytest tests/agent/test_m5d_grounding_candidates.py tests/agent/test_tool_loop.py tests/agent/test_p4_grounding.py -q`; commit `feat(agent): reuse extractive finalization for P5`.

### 3. Persist sanitized P5 diagnostics

**Files:** Add `src/verbaops/evaluation/p5_trace.py` and `tests/evaluation/test_p5_trace.py`; wire only required opt-in/run-directory values through the existing runtime/API assembly and public runner.

- **RED:** Test exact P5 fields: `knowledge_mode_active`, `knowledge_terminal_output_transport`, `provider_response_format_attached`, `tool_path_entered`, `extractive_mode_deactivated_after_tool`, `raw_terminal_content`, `json_parse_success`, `json_parse_failure_reason`, `schema_validation_result`, `proposed_claims`, `proposed_evidence_handle_per_claim`, `proposed_excerpt_per_claim`, `handle_validation_result_per_claim`, `excerpt_validation_result_per_claim`, `deterministic_rejection_reason_per_claim`, `rendered_final_claims`, `fallback_used`, and `fallback_reason`. Test runtime constants against the committed P5 plan for this field set, transport, and false response-format flag; simulate an image without the plan file and prove trace creation still works. Also test P5 label, knowledge/no-evidence/tool states, safe projection, path confinement, and hash-bound references.
- Implement a narrow P4-diagnostic-to-P5 projection and P5-only `p5-traces/` storage. Keep only minimal trace constants in runtime code; do not copy `evals/` into the image or read the plan dynamically. Do not rename P4 keys or add a general trace framework. Store no credentials, headers, prompts, or unrelated private data.
- **GREEN:** Run the P5 trace tests plus `tests/evaluation/test_p4_trace.py` and affected API/runtime tests; commit `feat(eval): persist P5-labelled canonical traces`.

### 4. Add P5 scorer-v2 reporting

**Files:** Modify `src/verbaops/evaluation/rag_grounding.py`; add `tests/evaluation/test_m5d_p5_scoring.py`.

- **RED:** Test P5 scoring uses each exact frozen fact fixture and scorer-v2 assessment for expected coverage and groundedness, reports P5 diagnostics/trust invariant, and does not alter P4 or historical scoring results.
- Add the smallest explicit P5 scoring entry point/projection over existing scorer-v2 logic. Do not change the scorer, fixtures, floors, or historical paths.
- **GREEN:** Run P5 scoring, P4 scoring, and scorer-v2 tests; commit `feat(eval): score P5 with frozen scorer-v2`.

### 5. Add P5 plan audit, identity, authorization, and canonical runner

**Files:** Add `src/verbaops/evaluation/m5d_b2_p5_preregistration.py` and `tests/evaluation/test_m5d_p5_run_identity.py`; extend `src/verbaops/evaluation/m5d_run_identity.py` and `scripts/run_m5d_grounded_eval.py` narrowly.

- **RED:** Test the P5 plan/hash audit and identity binding for dataset and knowledge-manifest hashes; P5 plan SHA; scorer version/definition/implementation/manifest/fixture/spec; local schema SHA; separate application, harness, and freeze SHAs; hosted CI run/head/conclusion/job hash; candidate/model/provider/capability; G2 and threshold; retrieval profile/strategy/final-five; prompt version/hash; graph/finalizer; transport; `tool_choice="auto"`; `provider_response_format_attached=false`; and run ID. Also test P4 remains closed; P5 is DEV-only; exact-identity resume rejects duplicates/replay and a second namespace.
- Add P5-specific authorization rather than routing through P4 closeout guards. Extend the public API runner for one 96-case DEV namespace, checkpoint validation, P5 traces, and complete-only scoring/reporting. Do not load holdout rows.
- **GREEN:** Run P5 identity/runner tests plus P4 identity/closeout and preregistration regressions; commit `feat(eval): authorize canonical P5 DEV runs`.

### 6. Add future Stage 4 support and freeze

**Files:** `scripts/run_m5d_stage4_dev_eval.py`, its focused tests, and only necessary contract wiring.

- **RED:** Test P5 passes Stage 4 candidate/profile preflight but cannot execute without complete eligible P5 evidence that passes every RAG floor and the zero-fabricated-handle invariant.
- Add P5 recognition only; do not run Stage 4. Review the branch for P4 preservation, P5-only labels, correct request delta, tool/budget invariants, identity/resume protection, and absence of holdout/result/selection paths.
- **GREEN:** Run focused P5/P4 tests and provider-free suites: `make m5d-evaluation-contract`, `make rag-evaluation-contract`, `make rag-unit-contract`, `make rag-contract`, `make knowledge-contract`, `make agent-acceptance`, `make commerce-contract-check`, `make check`, Ruff, Ruff format check, mypy, pre-commit, `git diff --check`, evaluation contracts, and runtime Docker build. Run DB-backed `make rag-contract` and `make knowledge-contract` locally when their required test database configuration is available. If the environment lacks the required database URL, record that fact without changing configuration or weakening tests; the corresponding hosted CI jobs must pass on the exact implementation-freeze head before inference authorization. Verify frozen hashes; commit `feat(eval): freeze provider-free P5 implementation`; push and require all 16 hosted jobs green on that exact head before any later inference authorization.

## Plan review checklist

- Every P5 plan requirement maps to a task; each behavior change begins with a failing test.
- P4 request/schema behavior, closeout, evidence, and historical scoring remain covered and unchanged.
- `response_format` omission is the only request delta; tools and `tool_choice="auto"` are fixed.
- P5 canonical artifacts are P5-labelled without a broad P4 refactor.
- No unnecessary abstraction, provider call, holdout access, or runtime implementation begins before this plan is approved.
