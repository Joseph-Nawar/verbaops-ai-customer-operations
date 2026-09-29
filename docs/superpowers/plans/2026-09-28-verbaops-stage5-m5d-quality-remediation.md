# Stage 5 M5D-A — RAG Failure Forensics & Evaluation Foundation

> **SINGLE-AGENT execution only. Use `superpowers:executing-plans` inline; subagents are forbidden.**

**Goal:** Preserve M5C and rag-v0.1 exactly while documenting its evidence-backed failure modes, authoring an independent 120-case rag-v0.2 corpus, and preregistering provider-agnostic M5D experiments.

**Architecture:** Keep M5D corpus parsing/audit and the fail-closed split guard in a new evaluation module. Bind immutable inputs with locked-base SHA-256 constants in provider-free tests. Store only preregistration in v0.2; there is no selection artifact or result. Add an isolated CI contract that audits the corpus, plan, guard, and protected file hashes without inference services.

**Tech Stack:** Python 3.12, Pydantic, pytest, committed NovaCommerce sources and chunker, Make, GitHub Actions, uv, Ruff, mypy, pre-commit.

**Spec:** User-provided M5D-A requirements in the active task.

## Global Constraints

- Work only on `stage5/m5d-rag-grounding-remediation`, based on locked main `5d0351a7f0dc05b87c2ab8dec0613dc48467b7d9`.
- Do not change any rag-v0.1 question, label, judgment, split, result, selection, baseline, threshold, or production profile. Five locked reference SHA-256 values are recorded in M5D contract tests.
- Do not alter production retrieval, prompt, model/provider, corpus/chunking, or five Commerce tools. Do not implement M5D-B/C or Stage 6.
- rag-v0.1 holdout is spent and may inform forensic analysis only. Describe no result as an improvement on an untouched v0.1 holdout.
- Do not execute rag-v0.2 release_holdout, call a provider, download a model, or create a fake selection artifact.
- The Qwen audit is local resource discovery only. No model downloads, hosted-CI inference, or runtime additions.
- Do not modify/delete pre-existing ignored or untracked user artifacts.

## Review Focus

Check at every step for: accidental edits to frozen files; query duplication after Unicode punctuation/case normalization; unsupported fact/locator claims; holdout access without provenance; CI coupling to any provider/runtime; and unsupported forensic counts where raw candidate/evidence data is unavailable.

## Execution Tasks

### 1. Verify and record locked inputs

- [x] Confirm `origin/main` is the locked commit, tracked worktree is clean, and create the requested branch.
- [x] Record locked SHA-256 values for v0.1 questions, manifest, selection, M5C baseline, and knowledge manifest.
- [x] Add hard-coded immutability tests for those values plus Stage 4 baseline, production retrieval profile/prompt, and five Commerce tool files.

### 2. Write diagnostic tests, then audit module

- [x] Add tests for exact counts/distribution, IDs, normalized intra/inter-version query uniqueness, punctuation/case rewrites, answerability, locator existence, expected-fact support, v0.2 version/manifest SHA, and failure cases.
- [x] Run focused tests to confirm new v0.2 interfaces fail before implementation.
- [x] Implement a separate `rag_v02` model/audit module and CLI. Reconstruct known locators and chunk text from committed knowledge sources and the locked chunker; validate every fact against its committed supporting chunk.
- [x] Author 120 corpus-grounded cases independently (90 answerable, 30 no-answer), compute manifest SHA, and pass the audit. Do not copy or paraphrase individual v0.1 holdout cases.

### 3. Seal v0.2 holdout and preregister experiments

- [x] Add tests for default DEV, refusal of release holdout with missing selection, and refusal of malformed or provenance-mismatched selection.
- [x] Implement a fail-closed guard; require future selection provenance bound to v0.2 dataset and knowledge-manifest SHA. No selection file is created in M5D-A.
- [x] Add exact-schema tests for G0/G1/G2, P0/P1/P2/P3, M0/M1, selection priorities, M5D targets, and future Stage 4 DEV security/tool guard.
- [x] Write `experiment-plan.json` with exact candidate definitions, locations, limits, and deterministic future selection rules. All entries are preregistration only.

### 4. Produce deterministic M5C postmortem and implementation plan

- [x] Read only committed M5C baseline and available sanitized artifacts. Cross-check baseline metrics against artifact summaries.
- [x] Count each supported failure class by DEV/spent-holdout and category; label raw evidence unavailable where top-20/pre-fusion/citations/chunk context do not support a deterministic classification. H is a separate evaluator-review flag. Do not change scores.
- [x] Explain the RRF score scale versus frozen threshold without recommending a production change.
- [x] Record local RAM/GPU/runtime availability without downloading/running a model; state if Qwen 30B is resource-blocked.
- [x] Write the minimum forensic report and this implementation plan. Clearly separate M5D-A, B, and C.

### 5. Provider-free CI and focused tests

- [x] Add `m5d-evaluation-contract` Make target and a standalone GitHub Actions job that invokes it without provider secrets/services.
- [x] Run v0.2 corpus audit, M5D contract, focused corpus/guard/plan/immutability tests, and requested existing contracts.
- [x] Run `make check`, Ruff, Ruff format, mypy, pre-commit, `git diff --check`, OpenAPI contract, and Docker runtime build.
- [x] Review changed-file list and hashes to prove frozen inputs are unchanged.

### 6. Publish draft for review, without merging

- [ ] Commit coherent M5D-A changes and push the requested branch.
- [ ] Open a draft PR against main; do not merge or begin M5D-B.
- [ ] Wait for fresh hosted CI on the exact pushed head and record every job conclusion.
- [ ] Return one evidence packet with all required hashes, counts, tests, CI, and scope confirmations.

## Verification Standard

Each newly added contract test must be run. Never claim a test, build, audit, CI job, or provider-free property without observed output. The final self-review is inline; do not delegate review to an agent.
