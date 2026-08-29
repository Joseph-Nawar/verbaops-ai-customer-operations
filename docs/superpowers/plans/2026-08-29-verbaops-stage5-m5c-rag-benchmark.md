# Stage 5 M5C — RAG Benchmark, Calibration & Evidence Implementation Plan

> **SINGLE-AGENT execution only. No subagents. Human architecture approval already granted.**

**Goal:** Measure the locked Stage 5 RAG system with a frozen 120-case benchmark, deterministic provider-free contracts, genuine TEI-backed development and holdout evidence when infrastructure permits, and an evidence-backed production retrieval profile.

**Architecture:** Keep benchmark concerns in the application-owned evaluation package and adapt the existing M5B retrieval primitives through one evaluation-owned strategy adapter. Freeze dataset and corpus provenance before execution, select and calibrate on dev only, enforce a fail-closed holdout guard, and serialize raw evidence separately from committed baseline summaries.

**Tech Stack:** Python, Pydantic/dataclasses already used by the repository, pytest, PostgreSQL/pgvector, Alembic 0005, Ruff, mypy, pre-commit, Docker Compose, genuine Hugging Face TEI, and the existing Stage 4 evaluation conventions.

**Spec:** User-provided M5C requirements in the active task conversation.

## Global Constraints

- SINGLE-AGENT execution only; no subagents and no subagent-driven-development.
- Locked base is `main @ 21f6c96f148e6e293b49ff4bcc6ee422ff7ac15a`.
- Do not modify corpus content, M5A chunking, Stage 4 baseline, five Commerce tools, M5B frozen parameters, migration 0005, or begin Stage 6.
- Benchmark version is `rag-v0.1`; dataset is exactly 120 cases: 96 `dev` and 24 `release_holdout`.
- Frozen retrieval parameters are dense 20, lexical 20, RRF `k=60`, fused 20, rerank top 20, final top 5.
- Holdout requires both `--split release_holdout` and a provenance-valid frozen `selection.json`; no holdout tuning.
- Real TEI uses the pinned image/model/revisions; provider-free CI never calls real TEI or real agents.
- If genuine TEI cannot be made healthy after one bounded attempt, do not execute holdout or claim Stage 5 complete.

---

### Task 1: Map the locked-base evaluation and retrieval interfaces

**Files:**
- Inspect: `src/verbaops/evaluation/`, `src/verbaops/retrieval/`, `knowledge/novacommerce/`, `tests/`, `Makefile`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the locked-base Stage 4 evaluation package, M5A corpus/chunker, and M5B retrieval/agent contracts.
- Produces: an exact file map and confirmed import/test seams used by Tasks 2–12.

- [ ] **Step 1: Record current branch, commit, status, migration heads, and existing contract commands.**
- [ ] **Step 2: Inspect corpus manifest/source versions, chunker constants, retrieval service signatures, and agent response/citation types.**
- [ ] **Step 3: Identify existing test fixtures and avoid changing the permanent M5A schema-0004 contract.**

### Task 2: Freeze the benchmark corpus and corpus-audit contract

**Files:**
- Create: `evals/rag/v0.1/manifest.json`
- Create: `evals/rag/v0.1/questions.jsonl`
- Create: `src/verbaops/evaluation/rag_models.py`
- Create: `src/verbaops/evaluation/rag_corpus.py`
- Create: `scripts/check_rag_eval_corpus.py`
- Test: `tests/evaluation/test_rag_corpus.py`

**Interfaces:**
- `load_rag_cases(path) -> list[RagCase]`
- `audit_rag_corpus(cases, knowledge_root) -> RagCorpusAudit`
- `RagCase`, `RelevanceJudgment`, `ExpectedFact`, and stable locator models.

- [ ] **Step 1: Write failing tests for exact counts, split/category allocation, unique IDs, duplicate normalized queries, valid/invalid locators, answerability/relevance invariants, fact support, version, and language.**
- [ ] **Step 2: Run `uv run pytest tests/evaluation/test_rag_corpus.py -q` and verify failures are due to missing models/audit behavior.**
- [ ] **Step 3: Author the 120 realistic English cases with stable logical locators and no-answer cases having zero positive judgments.**
- [ ] **Step 4: Implement strict parsing/audit against the committed NovaCommerce corpus and locked `MAX_CHUNK_TOKENS=180`, `OVERLAP_TOKENS=30`.**
- [ ] **Step 5: Run the focused corpus tests and `uv run python scripts/check_rag_eval_corpus.py`; record both SHA-256 values.**

### Task 3: Implement deterministic retrieval metrics and grounded-answer metrics

**Files:**
- Create: `src/verbaops/evaluation/rag_metrics.py`
- Test: `tests/evaluation/test_rag_metrics.py`

**Interfaces:**
- `recall_at_k(retrieved, judgments, k) -> float`
- `mean_reciprocal_rank(retrieved, judgments) -> float`
- `ndcg_at_k(retrieved, judgments, k) -> float`
- `macro_metric(values) -> float | None`
- `citation_precision(citations, judgments) -> MetricResult`
- `grounded_fact_score(answer, expected_facts, cited_locators) -> GroundednessResult`

- [ ] **Step 1: Write failing worked-example tests for Recall@1/@5, MRR, graded nDCG@5, macro denominators, citation precision, grounded facts, unsupported rate, and empty denominators.**
- [ ] **Step 2: Run the focused metrics tests and confirm the intended failures.**
- [ ] **Step 3: Implement pure deterministic formulas with explicit denominators and no cross-strategy score comparison.**
- [ ] **Step 4: Run focused metrics tests and retain exact counts in report-ready result objects.**

### Task 4: Add the M5B strategy adapter and latency/result models

**Files:**
- Create: `src/verbaops/evaluation/rag_runner.py`
- Test: `tests/evaluation/test_rag_strategies.py`

**Interfaces:**
- `RetrievalStrategy` enum: `dense`, `lexical`, `hybrid_rrf`, `hybrid_rrf_rerank`.
- `FrozenRetrievalParameters` with dense/lexical/RRF/fused/rerank/final limits.
- `EvaluationRetrievalAdapter.retrieve(query, tenant_id, strategy) -> RetrievalRun`.

- [ ] **Step 1: Write failing tests proving all four strategies call the existing M5B primitives, preserve stable locators, and honor frozen limits.**
- [ ] **Step 2: Run focused strategy tests and verify missing adapter behavior.**
- [ ] **Step 3: Implement one adapter over existing dense, lexical, RRF, and reranker primitives plus per-stage timing.**
- [ ] **Step 4: Run focused strategy tests and test tenant/active-version/security invariants through the adapter.**

### Task 5: Implement dev-only selection, deterministic calibration, and fail-closed holdout guard

**Files:**
- Modify: `src/verbaops/evaluation/rag_runner.py`
- Create: `src/verbaops/evaluation/rag_reports.py`
- Create: `evals/rag/v0.1/selection.json` only after real dev selection/calibration
- Test: `tests/evaluation/test_rag_calibration.py`
- Test: `tests/evaluation/test_rag_holdout_guard.py`

**Interfaces:**
- `select_strategy(dev_metrics) -> SelectionDecision`
- `calibrate_threshold(dev_observations) -> CalibrationResult`
- `validate_holdout_provenance(selection, dataset_sha, knowledge_sha, labels/config) -> None`
- `run_benchmark(..., split="dev", selection_path=None) -> BenchmarkReport`

- [ ] **Step 1: Write failing tests for the pre-registered tie rules, 90% no-answer eligibility, best answerable acceptance, deterministic ties, explicit calibration failure, and every holdout refusal condition.**
- [ ] **Step 2: Run focused calibration/guard tests and verify failures.**
- [ ] **Step 3: Implement dev-only strategy ordering, observed-score threshold enumeration, frozen selection serialization, and default `--split dev`.**
- [ ] **Step 4: Implement the two-flag holdout requirement and SHA/strategy/threshold/labels/config checks.**
- [ ] **Step 5: Run focused tests plus provider-free fake benchmark execution; do not touch holdout before selection is produced.**

### Task 6: Add provider-free `rag-evaluation-contract`

**Files:**
- Create: `tests/evaluation/test_rag_evaluation_contract.py`
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: corpus audit, metrics, adapter, calibration, guard, and report serializers.
- Produces: a separate permanent provider-free hosted job named `rag-evaluation-contract`.

- [ ] **Step 1: Write contract tests for corpus SHA/version invariants, formulas, RRF adapter, fake benchmark, calibration, guard, reports, citation precision, and groundedness.**
- [ ] **Step 2: Run the contract locally and verify failures for unimplemented pieces.**
- [ ] **Step 3: Wire the provider-free command into `Makefile` and a separate CI job without changing `knowledge-contract`, `rag-contract`, or `evaluation-contract`.**
- [ ] **Step 4: Run the complete provider-free contract and inspect the CI YAML for no real-provider calls.**

### Task 7: Add reproducible genuine-TEI ingestion and benchmark scripts

**Files:**
- Create: `scripts/run_rag_benchmark.py`
- Create: `scripts/run_rag_grounded_eval.py`
- Modify: `src/verbaops/evaluation/rag_runner.py` as required by confirmed M5B APIs
- Test: `tests/evaluation/test_rag_scripts.py`

**Interfaces:**
- `run_rag_benchmark.py --split dev` is the default.
- `--split release_holdout` requires `--selection evals/rag/v0.1/selection.json`.
- Grounded runner checkpoints each case without persisting credentials.

- [ ] **Step 1: Write failing parser/guard/checkpoint tests.**
- [ ] **Step 2: Run focused script tests and verify failures.**
- [ ] **Step 3: Implement real M5B ingestion of all 17 source versions into fresh schema-0005 PG/pgvector and report counts/model/profile/dim/SHA.**
- [ ] **Step 4: Implement benchmark and grounded-run checkpoint/output paths under uncommitted `artifacts/rag_eval_runs/<run_id>/`.**
- [ ] **Step 5: Run provider-free script tests; reserve real execution for the bounded TEI gate after all code is green.**

### Task 8: Run the genuine TEI health gate and dev benchmark

**Files:**
- Use existing: Compose/runtime configuration and local environment; no credential files committed.
- Create only uncommitted: raw health/dev artifacts under `artifacts/rag_eval_runs/<run_id>/`.

- [ ] **Step 1: Start the pinned TEI embedding/reranker services with the exact image/model revisions and bounded timeout.**
- [ ] **Step 2: Prove embedding/reranker health, LiteLLM route health, exact 768-dimensional E5 response, and valid rerank scores without logging secrets.**
- [ ] **Step 3: Ingest fresh schema-0005 DB and verify deterministic chunk total and lifecycle counts before evaluating.**
- [ ] **Step 4: Run only the 96 dev cases for all four strategies; select and calibrate deterministically.**
- [ ] **Step 5: Write and freeze `selection.json` only after dev evidence is complete.**

### Task 9: Freeze production retrieval profile and run untouched release holdout

**Files:**
- Modify: production retrieval profile/service only if selected strategy differs from current M5B default.
- Create: `evals/rag/v0.1/selection.json`
- Create: `evals/baselines/stage5-rag-v0.1-baseline.json`
- Create: `evals/baselines/stage5-rag-v0.1-baseline.md`

- [ ] **Step 1: Add a failing exact-profile regression test for `knowledge-retrieval-v1.1`, selected strategy, frozen limits, model/profile, and threshold.**
- [ ] **Step 2: Run it RED, then minimally freeze the selected configuration after dev selection.**
- [ ] **Step 3: Verify selection provenance and execute the 24-case holdout once for all four strategies.**
- [ ] **Step 4: Report production-candidate metrics separately without tuning labels, thresholds, queries, or models.**

### Task 10: Run genuine grounded-answer evaluation and serialize Stage 5 evidence

**Files:**
- Use: `scripts/run_rag_grounded_eval.py`
- Create: committed baseline JSON/Markdown; uncommitted raw per-case artifacts.

- [ ] **Step 1: Run selected configuration through the real `agent-fast` path only when credentials are available locally.**
- [ ] **Step 2: Capture answer/citation/evidence/invocation/latency/model/provider/cost metadata with durable checkpoints and no secrets.**
- [ ] **Step 3: Compute deterministic citation precision, expected-fact coverage, groundedness, unsupported-claim rate, abstention, answer p50/p95, and cost metadata coverage.**
- [ ] **Step 4: Write baseline JSON and a factual Markdown report answering every required review question and limitation.**

### Task 11: Full verification, review, push, and hosted evidence handoff

**Files:**
- Inspect: all changed files and final git diff.

- [ ] **Step 1: Run corpus audit, all RAG tests/contracts, M5A knowledge-contract, M5B rag-contract, Stage 4 evaluation-contract, agent acceptance, and regression tests.**
- [ ] **Step 2: Run `make check`, Ruff, format check, mypy, pre-commit, `git diff --check`, OpenAPI, Docker runtime build, and Compose profile validation.**
- [ ] **Step 3: Perform exactly one bounded TEI retry if the first genuine gate was externally blocked; record sanitized failure/stall point and do not loop.**
- [ ] **Step 4: Re-read the plan/spec, verify Stage 4/M5A/tool/migration invariants, and inspect credentials with secret-safe checks.**
- [ ] **Step 5: Commit focused changes, push `stage5/m5c-rag-benchmark`, open a Draft PR, and wait for the fresh hosted CI run on the exact head.**
- [ ] **Step 6: Return one evidence packet with SHAs, test counts, metrics, TEI/holdout status, every hosted job conclusion, and explicit blocked/complete status.**

## Self-review checklist

- [ ] Dataset and audit requirements map to Task 2.
- [ ] All four frozen strategies and deterministic metrics map to Tasks 3–4.
- [ ] Dev-only selection, calibration, and fail-closed holdout map to Task 5.
- [ ] Separate provider-free and PostgreSQL contracts remain distinct in Tasks 6 and 11.
- [ ] Genuine TEI/DB/agent execution and bounded external failure handling map to Tasks 7–10.
- [ ] Baselines, production profile, and final verification map to Tasks 9–11.
- [ ] No Stage 6, M5C migration, corpus/chunker edit, tool edit, or unrelated refactor is authorized.
