# Stage 5 M5D-B DEV Remediation Implementation Plan

> **For agentic workers:** Use this plan inline in one agent session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure preregistered evidence-gate, grounding, and model candidates on rag-v0.2 DEV only, then record an auditable DEV decision without opening holdout or changing production defaults.

**Architecture:** Freeze the experiment plan as schema v1.1, tests, and a plan document in a dedicated pre-experiment commit. Push that commit and wait for fresh green hosted CI before any provider inference. Implement evaluation-only candidate injection with production defaults unchanged, run against an isolated database with resumable artifacts, and record a hash-bound DEV decision that the release-holdout guard does not accept.

**Tech Stack:** Python 3.12, Pydantic, FastAPI/LangGraph, SQLAlchemy/PostgreSQL with pgvector, pytest, Ruff, mypy, uv, GitHub Actions.

**Spec:** User-supplied M5D-B brief attached to the task.

## Global Constraints

- Base and branch are `0be9e43021beac020c29dc67d54fc367a7c31480` and `stage5/m5d-b-dev-remediation`.
- Never execute `rag-v0.2` `release_holdout`; never create `selection.json` or unlock the holdout guard.
- Do not modify rag-v0.1, its labels/results, production retrieval profile/threshold, system_v2, agent-fast, corpus/chunking, or the five Commerce tools.
- Keep current production hybrid RRF ranking, candidate evidence, threshold `0.032018442622950824`, graph, prompt, and runtime defaults unchanged.
- No LLM judge, Qwen download/substitution, Stage 4 release-holdout use, M5D-C, or Stage 6.
- No provider inference before the B0 pre-experiment commit has fresh green hosted CI.
- Record credentials only as presence/absence; never print, persist, or log secrets.
- All genuine candidate measurements are DEV-only, use the real public application path where practical, and have checkpointed application-owned trace provenance.

## Review Focus

- Missing evidence or a failed score must reject the turn; test absent and non-finite confidence.
- G1 must score stored E5 vectors for the same final five, including lexical-only entrants; test that its candidate set cannot drift.
- Candidate threshold selection must preserve the 90% no-answer guard and deterministic tie order; test ties and ineligible gates.
- P2/P3 may only fail closed on pure knowledge turns; test tool-bearing turns and exact one-repair exhaustion.
- Interrupted DEV runs must resume by case ID without duplicate provider calls or credentials in artifacts; test checkpoint integrity and sanitization.

---

### Task 0: Pre-experiment preregistration freeze

**Files:**
- Modify: `evals/rag/v0.2/experiment-plan.json`
- Modify: `src/verbaops/evaluation/rag_v02.py`
- Modify: `tests/evaluation/test_rag_v02_contract.py`
- Create: `docs/superpowers/plans/2026-09-29-verbaops-stage5-m5d-b-dev-remediation.md`

**Interfaces:**
- Preserve current plan validation and holdout artifact schema; strengthen exact M5D-B rules and set `m5d-experiment-plan-v1.1`.
- `guard_rag_v02_split("dev")` remains the default; no holdout artifact is created.

- [ ] Write provider-free tests for schema v1.1, exact threshold/grounding/model selection order, M0-first execution policy, run provenance requirements, and fail-closed holdout state.
- [ ] Run the focused contract and confirm the new assertions fail before updating implementation/schema.
- [ ] Update the preregistration JSON and validator to make every threshold-selection, eligibility, latency, quality, Stage 4 guard, and stop condition explicit.
- [ ] Run `make m5d-evaluation-contract` and the focused tests; record the resulting plan SHA in the B0 commit metadata/PR description.
- [ ] Commit only the preregistration, validator, tests, and this plan as `test: freeze M5D-B dev experiment contract`.
- [ ] Push the branch, open/update its DRAFT PR, and wait for all fresh hosted CI jobs on the exact commit to pass before any provider request.

### Task 1: Deterministic evidence-gate scoring and selection

**Files:**
- Create or modify: `src/verbaops/evaluation/rag_v02_gates.py`
- Create or modify: `tests/evaluation/test_rag_v02_gates.py`
- Create or modify: `scripts/run_m5d_gate_eval.py`
- Modify: `Makefile` only for provider-free audit targets when needed.

**Interfaces:**
- Represent a DEV observation as case ID, answerability, nullable candidate confidence, and measured candidate-specific latency components.
- Return per-candidate threshold metrics, eligibility, selected threshold, candidate selection trace, and candidate-specific p50/p95.

- [ ] Write failing tests for G0/G1/G2 confidence aggregation, missing-score rejection, inclusive threshold boundary, enumerated thresholds, tie order, and the >=22/24 no-answer guard.
- [ ] Implement pure scoring/selection helpers; do not compare raw scales across gates.
- [ ] Build the real-TEI DEV collector over the frozen hybrid retrieval result and exact final five candidates. G1 uses the query embedding and each selected chunk's stored E5 embedding, including lexical entrants. G2 calls the pinned cross-encoder only on those five and never reranks.
- [ ] Record hybrid retrieval, gate component, and total latency separately with model/revision and artifact hashes.
- [ ] Verify by mocked/provider-free tests; do not run inference before Task 0 CI is green.

### Task 2: Evaluation-only grounding candidates

**Files:**
- Create: `src/verbaops/agent/prompts/system_v3.txt`
- Modify: `src/verbaops/agent/prompts/__init__.py`, `src/verbaops/agent/graph.py`, `src/verbaops/agent/context.py`, `src/verbaops/agent/runtime.py`, and `src/verbaops/retrieval/grounding.py` as required.
- Create or modify: focused agent grounding tests.

**Interfaces:**
- Production constructors keep current prompt/finalizer behavior by default.
- Evaluation candidates are code-owned identifiers `P0_CURRENT`, `P1_PROMPT_V3`, `P2_FAIL_CLOSED_CITATIONS`, and `P3_ONE_REPAIR_THEN_FAIL_CLOSED`; no arbitrary prompt path or public production setting.

- [ ] Write failing tests for system_v3 trust/citation instructions, P2 safe fallback only on accepted-evidence pure-knowledge turns with zero valid citation, and P3 at-most-one bounded text-only repair followed by fail-closed fallback.
- [ ] Add opt-in candidate policies while preserving system_v2 and the current finalizer as defaults.
- [ ] Ensure repair cannot call Commerce tools, modify business state, add unsupported facts, or run twice; record sanitized repair/fallback counters.
- [ ] Run provider-free grounding and agent security tests.

### Task 3: Isolated, resumable DEV evaluation harness

**Files:**
- Create or modify: `scripts/run_m5d_grounded_eval.py`, DEV-only artifact helpers under `src/verbaops/evaluation/`, and focused tests.
- Modify only evaluation setup paths required to create an isolated database and ingest the frozen corpus through `KnowledgeService` and genuine E5 embeddings.

**Interfaces:**
- The runner accepts only `--split dev`, enforces the v0.2 guard, writes checkpoints below `evals/rag/v0.2/dev-evidence/`, and stores larger raw traces under ignored `artifacts/m5d/`.
- Restart skips complete validated case IDs and never serializes credential fields.

- [ ] Write failing tests for DEV-only split enforcement, 96-case checkpoint resume, duplicate/corrupt checkpoint rejection, secret-key omission, and required evaluation provenance.
- [ ] Prepare an isolated evaluation DB at migration `0005_retrieval_grounding_v1` with the exact corpus/cardinality/profile requirements; never reset unrelated local state.
- [ ] Execute real M0 gate collection after the CI gate; if the pinned TEI services cannot coexist, use preregistered SHA-bound phases and preserve exact candidate identity.
- [ ] If no gate meets >=90% no-answer rejection, record the stop condition and do not proceed to grounding/model evaluation.

### Task 4: Grounding and model bake-off on DEV

**Files:**
- Modify: `scripts/run_m5d_grounded_eval.py` and evaluation reporting/metrics modules.
- Create: `evals/rag/v0.2/dev-evidence/` checkpoints and summaries; larger sanitized traces live under ignored `artifacts/m5d/`.

**Interfaces:**
- Run P0–P3 only for the selected eligible gate, beginning with M0 `groq/openai/gpt-oss-120b`.
- M1 `Qwen/Qwen3-30B-A3B-Instruct-2507` runs only if its separately configured local endpoint is executable; otherwise record `M1_NOT_EXECUTED_LOCAL_RESOURCE_BLOCK` and retain M0 without claiming a comparison.

- [ ] Write provider-free tests for all grounding thresholds, deterministic tie hierarchy, cost coverage, and candidate ineligibility.
- [ ] Run all 96 DEV cases with checkpointing for each preregistered executable P/M combination through the actual public app path and application-owned traces.
- [ ] Report citation precision, labeled groundedness, unsupported recognized units, expected-fact coverage, accepted-evidence citation compliance, fallback/repair counts, model/tool call counts, answer p50/p95, and cost coverage.
- [ ] Stop with `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE` if no grounding candidate meets all preregistered quality floors.
- [ ] Run Stage 4 DEV regression only for RAG-qualified candidates and apply all preregistered security and regression limits; never use Stage 4 release holdout.

### Task 5: DEV decision and final verification

**Files:**
- Create: `evals/rag/v0.2/dev-decision.json`
- Create: `docs/evaluation/stage5-m5d-b-dev-results.md`
- Modify: tests for decision provenance and holdout denial.

**Interfaces:**
- Decision provenance binds the v0.2 corpus, knowledge manifest, experiment plan, PRE_EXPERIMENT_SHA, evaluated code SHAs, run IDs, and artifact hashes.
- `dev-decision.json` is not `selection.json` and must be rejected by the release-holdout guard.

- [ ] Write failing tests for exact hashes, `holdout_executed=false`, `production_promoted=false`, and rejection of a DEV decision by the holdout guard.
- [ ] Produce the deterministic DEV-only decision/result report with no performance claim about an untouched holdout.
- [ ] Run M5D, RAG, knowledge, evaluation, and agent acceptance contracts; `make check`; Ruff, format, mypy, pre-commit, diff check, OpenAPI contract, and Docker runtime build.
- [ ] Push the same branch, keep its PR in draft, and wait for fresh hosted CI on the exact final head. Report every job conclusion; do not merge.
