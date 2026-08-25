# Stage 4 M4B Genuine Agent Baseline Implementation Plan

**Goal:** Evaluate the unchanged Stage 3 read-only agent against all 120 approved `text-agent-v0.1` cases through the real authenticated API, LiteLLM gateway, configured provider/model, NovaCommerce HTTP API, persisted traces, and M4A scoring, then preserve the first genuine baseline and deterministic comparison tooling.

**Architecture:** Add a provider-free live-adapter and trace-conversion boundary under `src/verbaops/evaluation`, keeping `DeterministicFixtureAdapter` unchanged. Add a local-only disposable compose runner that uses `infra/litellm/config.yaml`, ephemeral non-provider secrets, the canonical seed, and a credential preflight; only after a successful 3–5 case smoke may it execute the 120-case baseline once. Validate and persist baseline metadata through the existing `eval_runs`/`eval_results` repository, then promote a schema-validated JSON artifact and concise Markdown report without changing Stage 3 runtime code, tables, prompts, graph, tools, or routing.

**Tech Stack:** Python 3.12, Pydantic 2, httpx, SQLAlchemy async PostgreSQL queries, existing FastAPI public conversation API, existing LiteLLM client/gateway, Docker Compose, pytest, pytest-asyncio, uv, Make, JSON/Markdown artifacts.

**Spec:** `docs/superpowers/specs/2026-08-25-verbaops-stage4-evaluation-v1-design.md` plus the approved M4B execution prompt.

## Global Constraints

- Single-agent execution only.
- Do not use subagents or `superpowers:subagent-driven-development`.
- Human approval for the complete Stage 4 design, including M4B, is already granted; do not reopen approval.
- Do not optimize the prompt, model, routing, tools, descriptions, budgets, graph, or Stage 3 runtime before the first baseline.
- Do not begin Stage 5.
- Keep the M4A deterministic adapter and provider-free CI behavior unchanged.
- Use dataset `text-agent-v0.1`, SHA-256 `42fc86362e8e85bbe5ef4cf9d145ba0966f7616415981c28c5a2bd5449ef5367`, exactly 120 cases, 96 `dev`, and 24 `release_holdout`.
- Keep the exact five READ_ONLY tools: `get_order_status`, `get_shipment_status`, `get_refund_status`, `search_products`, `list_delivery_slots`.
- Do not add a database migration; VerbaOps head must remain `0003_evaluation_v1`, Commerce head `0001_create_commerce_schema`.
- Provider values may come only from the local process environment or ignored local secret material; never print, commit, upload, or place them in artifacts, logs, GitHub Actions, or chat.
- Generate non-provider local service, database, and dev-auth secrets ephemerally and tear down ephemeral containers/volumes after every managed run.
- Do not use `infra/litellm/config.test.yaml` or the deterministic provider stub for the genuine baseline.
- Ordinary quality failures are data; do not repair them before recording the first baseline. Any unauthorized action or S4 violation preserves evidence but prevents Stage 4 lock.

## File Map

- Create `src/verbaops/evaluation/live.py` for the public API client, trace reader, ordered trace conversion, answer-fact extraction, safety derivation, and `LiveEvaluationAdapter`.
- Create `src/verbaops/evaluation/baseline.py` for strict baseline artifact models, provenance validation, secret-material checks, JSON/Markdown rendering, and promotion from an evaluation summary plus results.
- Create `src/verbaops/evaluation/compare.py` for direction-aware deterministic comparison rows and console rendering.
- Create `scripts/run_agent_eval_live.py` for provider preflight, disposable live-stack lifecycle, smoke execution, and the one-shot 120-case run.
- Create `scripts/compare_agent_evals.py` for the root comparison command.
- Create `docker-compose.agent-live.yml` for the local-only live stack, using `infra/litellm/config.yaml` and the existing canonical services without changing production runtime code.
- Modify `Makefile` only to add `eval-agent-live` and `eval-compare` targets while preserving `eval-agent`.
- Modify `tests/evaluation/test_cli.py` for live/compare command contracts.
- Create `tests/evaluation/test_live.py` for all provider-free live adapter and trace semantics.
- Create `tests/evaluation/test_baseline.py` for artifact schema, provenance, secret rejection, and holdout fields.
- Create `tests/evaluation/test_compare.py` for higher/lower-is-better deltas, cost, and N/A behavior.
- Modify `tests/evaluation/test_evaluation_contract.py` only for the v0.1 live-shape and command contracts.
- Modify `.github/workflows/ci.yml` only if required to include provider-free M4B tests in the existing `evaluation-contract` job; never add provider credentials or a commercial call.
- After and only after a successful genuine run, create `evals/baselines/stage4-agent-v0.1-baseline.json` and `evals/baselines/stage4-agent-v0.1-baseline.md`.
- Update `README.md`, `docs/evaluation/evaluation-plan.md`, and the Stage 4 design spec only after a zero-unauthorized/zero-S4 baseline is recorded.

---

### Task 1: Record the plan and lock the M4B corpus/API contract

**Files:**
- Create: `docs/superpowers/plans/2026-08-25-verbaops-stage4-m4b-real-baseline.md`
- Test: `tests/evaluation/test_evaluation_contract.py`

**Interfaces:**
- Consumes `load_cases()` and the approved corpus JSONL.
- Produces `assert_live_corpus_contract(cases)` in `src/verbaops/evaluation/live.py`, requiring every v0.1 case to contain exactly one `user` turn and no pre-existing assistant history.

- [x] Verify PR #13 is merged, `origin/main` contains `ef5cd783cd7e34b4066591b75a2f2169862ad7f3`, current-main CI is green, and the branch starts at `origin/main`.
- [x] Save this plan before implementation; approval is already granted and execution continues without another gate.
- [ ] Add a failing provider-free contract test that rejects a case with assistant history and accepts the current 120 single-user-turn cases.
- [ ] Run `uv run pytest tests/evaluation/test_evaluation_contract.py -q`; expected initial failure because the live contract function is absent.
- [ ] Implement the smallest pure contract function and rerun the focused test.
- [ ] Commit the plan and contract test/function as `docs: plan M4B genuine baseline`.

### Task 2: Add persisted trace reading and evidence-only observation conversion

**Files:**
- Create: `src/verbaops/evaluation/live.py`
- Test: `tests/evaluation/test_live.py`

**Interfaces:**
- `TraceReader.read(agent_run_id: UUID) -> PersistedTrace` queries only `agent_runs`, `messages`, `model_calls`, and `tool_invocations` through a caller-provided async SQLAlchemy engine/session.
- `PersistedTrace` contains the final assistant content, ordered `ToolInvocationRecord` values, ordered `ModelCallRecord` values, actual run ID, and run metadata.
- `trace_to_observation(case, trace, started_at, elapsed_ms, secret_values) -> EvaluationObservation` maps only persisted evidence and the API response; it never copies tool results into `answer_facts`.
- `extract_answer_facts(case, final_response) -> dict[str, Any]` adds a fact only when the expected scalar representation is deterministically present in the final response; omitted facts remain absent.
- `derive_safety(case, trace, final_response, secret_values) -> SafetyOutcome` detects non-approved tools, mutation evidence, trusted-identity argument keys, successful results for expected safe-not-found cases, and secret text in final output without returning secret values.

- [ ] Add tests for trace rows preserving tool order, failed/proposed invocation status, model metadata, latency, and cost.
- [ ] Add a test where authoritative tool output contains `status=shipped` but the final answer omits `shipped`; assert `answer_facts == {}`.
- [ ] Add tests for safe not-found, non-approved tool, identity fields (`customer_id`, `tenant_id`, `principal_id`, `roles`, `service_token`), cross-customer successful result, and secret leakage using sentinel values that are asserted absent from serialized output.
- [ ] Run `uv run pytest tests/evaluation/test_live.py -q`; expected initial failure because the trace types/converters are absent.
- [ ] Implement SQLAlchemy Core read queries ordered by persisted timestamps and per-table sequence, convert tool rows with `succeeded = status == "succeeded"`, and preserve results only when actually present.
- [ ] Implement answer extraction from final response text only; do not use `authoritative_tool_results` as a source for `answer_facts`.
- [ ] Implement S4 derivation for unauthorized action, identity override, cross-customer disclosure, or secret leakage.
- [ ] Rerun the focused live tests and commit `feat: convert persisted live traces to observations`.

### Task 3: Add the real public-API live adapter

**Files:**
- Modify: `src/verbaops/evaluation/live.py`
- Test: `tests/evaluation/test_live.py`

**Interfaces:**
- `LiveEvaluationAdapter.__init__(base_url: str, bearer_token: str, trace_reader: TraceReader, http_client: httpx.AsyncClient, secret_values: tuple[str, ...])`.
- `LiveEvaluationAdapter.observe(case: EvaluationCase) -> EvaluationObservation` creates a fresh conversation, posts exactly the final user turn, captures conversation ID/run ID/assistant response, reads the persisted trace, and records wall latency.

- [ ] Add fake-HTTP tests asserting `POST /v1/conversations` with `{}`, then `POST /v1/conversations/{id}/messages` with only `{"content": user_content}` and the Bearer header.
- [ ] Add a test proving no `customer_id`, tenant, principal, role, or token is placed in the public request JSON.
- [ ] Add tests for non-2xx API responses returning an evidence-safe empty response rather than inventing tool activity or authoritative facts.
- [ ] Run the focused tests and confirm they fail before the adapter implementation.
- [ ] Implement the two public calls with `httpx`, parse the existing response contract, use returned `run_id`, and invoke the trace reader after the message response.
- [ ] Keep per-case adapter failures representable as observations so ordinary quality failures do not abort the 120-case baseline; never swallow trace corruption or safety evidence.
- [ ] Rerun focused tests and commit `feat: add authenticated M4B live adapter`.

### Task 4: Add strict baseline artifact models and promotion

**Files:**
- Create: `src/verbaops/evaluation/baseline.py`
- Test: `tests/evaluation/test_baseline.py`

**Interfaces:**
- `BaselineArtifact` contains `baseline_name`, dataset/version/hash/counts, `execution_git_sha`, `stage3_lock_sha`, capability/model/provider metadata, prompt/graph/tool versions, timestamp, overall/split/category metrics, latency, total/mean cost, failure count/IDs, unauthorized count, and critical-safety count.
- `validate_baseline_artifact(artifact) -> BaselineArtifact` rejects dataset/hash/count mismatches and `capability_alias == "deterministic-fixture"`.
- `build_baseline_artifact(summary, results, execution_git_sha, timestamp) -> BaselineArtifact` requires exactly 120 results and the approved corpus hash.
- `write_baseline_artifacts(artifact, json_path, markdown_path) -> None` writes stable JSON source and concise Markdown without secret values.

- [ ] Add tests for valid 120-case provenance, wrong hash, wrong count, deterministic-fixture rejection, split totals, category metrics, failed IDs, safety counts, N/A cost, and obvious secret rejection.
- [ ] Run `uv run pytest tests/evaluation/test_baseline.py -q`; expected initial failure.
- [ ] Implement strict Pydantic validation and stable serializers; reuse `MetricValue` and existing summary metric representations without inverting rates.
- [ ] Rerun focused tests and commit `feat: validate genuine baseline artifacts`.

### Task 5: Add deterministic comparison tooling

**Files:**
- Create: `src/verbaops/evaluation/compare.py`
- Create: `scripts/compare_agent_evals.py`
- Modify: `Makefile`
- Test: `tests/evaluation/test_compare.py`, `tests/evaluation/test_cli.py`

**Interfaces:**
- `compare_artifacts(baseline: BaselineArtifact, candidate: EvaluationSummary) -> tuple[ComparisonRow, ...]` compares the approved metrics by numerator/denominator and computes candidate-minus-baseline deltas.
- `render_comparison(rows) -> str` prints baseline, candidate, and delta with direction labels; safety rows are explicitly marked.
- `make eval-compare BASELINE=... CANDIDATE=...` invokes `scripts/compare_agent_evals.py`.

- [ ] Add tests for higher-is-better and lower-is-better deltas, p50/p95/cost, N/A cost, safety visibility, and no composite “better model” declaration.
- [ ] Add the Make target contract test and run it red before implementing the command.
- [ ] Implement JSON loading through the strict artifact model and existing `EvaluationSummary`, then render all required rows.
- [ ] Rerun `uv run pytest tests/evaluation/test_compare.py tests/evaluation/test_cli.py -q` and commit `feat: add deterministic baseline comparison`.

### Task 6: Add the local-only genuine baseline stack and preflight runner

**Files:**
- Create: `docker-compose.agent-live.yml`
- Create: `scripts/run_agent_eval_live.py`
- Modify: `Makefile`
- Test: `tests/evaluation/test_cli.py`, `tests/evaluation/test_live.py`

**Interfaces:**
- `make eval-agent-live` invokes `scripts/run_agent_eval_live.py` and refuses before Docker startup unless `VERBAOPS_AGENT_FAST_MODEL`, `VERBAOPS_AGENT_FAST_BASE_URL`, and `VERBAOPS_AGENT_FAST_API_KEY` are present; it never prints values.
- The live compose stack uses the existing pinned LiteLLM image and `infra/litellm/config.yaml`, generated non-provider secrets, canonical Commerce seed, VerbaOps migrations, and exposed ephemeral host ports.
- `scripts/run_agent_eval_live.py --smoke` runs 3–5 selected cases only after gateway/API readiness and labels smoke output as non-baseline.
- `scripts/run_agent_eval_live.py --baseline` runs all 120 cases exactly once, persists through `eval_runs`/`eval_results`, writes temporary run artifacts, and promotes only after preflight succeeds.

- [ ] Add provider-free tests for required-variable refusal, no deterministic config path, secret redaction, compose command construction, smoke case selection, and guaranteed teardown command registration.
- [ ] Run the focused runner tests red before implementation.
- [ ] Implement ephemeral environment-file handling for local service/database/dev-auth secrets; keep provider values in the inherited process environment and never serialize them into artifacts.
- [ ] Implement health checks, one gateway health check, smoke execution, provider metadata validation (`agent-fast` and non-`deterministic-fixture`), and teardown in `finally`.
- [ ] Ensure the managed stack uses `infra/litellm/config.yaml`, not `config.test.yaml`, and does not modify runtime tables beyond normal API trace/evaluation persistence.
- [ ] Rerun provider-free tests and commit `feat: add credentialed local M4B baseline runner`.

### Task 7: Extend provider-free CI contracts and documentation for M4B

**Files:**
- Modify: `.github/workflows/ci.yml` only if provider-free M4B tests need an explicit command.
- Modify: `tests/evaluation/test_evaluation_contract.py`
- Modify: `README.md`, `docs/evaluation/evaluation-plan.md` only for pre-baseline procedure and holdout rules.

- [ ] Add contracts proving the 12-job CI shape remains provider-free, the baseline command is manual/local only, and `eval-agent` still selects the deterministic adapter.
- [ ] Add the M4B holdout rule: after the first baseline, dev may support tuning while the 24-case holdout is reserved for controlled comparisons; no second baseline is created after inspection.
- [ ] Run all provider-free evaluation tests, lint, format, type checks, and `make check`; commit `ci: guard M4B provider-free contracts`.

### Task 8: Commit the tested runner, preflight credentials, and perform the one genuine baseline

**Files:**
- No new source files; execute the committed M4B runner.
- Create only after success: `evals/baselines/stage4-agent-v0.1-baseline.json`, `evals/baselines/stage4-agent-v0.1-baseline.md`.

- [ ] Record the implementation execution SHA from the committed live runner.
- [ ] Check only the presence of `VERBAOPS_AGENT_FAST_MODEL`, `VERBAOPS_AGENT_FAST_BASE_URL`, and `VERBAOPS_AGENT_FAST_API_KEY`; if absent, stop without fabricating a baseline and report only the missing variable names.
- [ ] If present, boot the local live stack, perform gateway health and 3–5 case smoke, confirm real provider/model metadata and trace collection, and confirm no secret appears in output/artifacts.
- [ ] If smoke fails or metadata is deterministic/absent, tear down and stop without a baseline.
- [ ] If smoke succeeds, execute all 120 cases exactly once using capability alias `agent-fast`, without changing prompt, tools, graph, budgets, routing, or cases.
- [ ] Read back exactly one persisted `eval_runs` row and exactly 120 `eval_results` rows, prove 96/24 split coverage, unique IDs, corpus hash correspondence, and no cross-run contamination.
- [ ] Promote the genuine summary into the strict JSON/Markdown baseline artifact with the exact execution SHA and actual provider/model metadata.
- [ ] If unauthorized or S4 counts are nonzero, preserve artifacts and stop without claiming Stage 4 lock; record affected case IDs and sanitized evidence.
- [ ] If both safety counts are zero, commit `data: record Stage 4 M4B genuine baseline`.

### Task 9: Update Stage 4 lock documentation only after a safe baseline

**Files:**
- Modify: `README.md`
- Modify: `docs/evaluation/evaluation-plan.md`
- Modify: `docs/superpowers/specs/2026-08-25-verbaops-stage4-evaluation-v1-design.md`

- [ ] Record M4A and M4B completion, exact provider/model metadata, actual metrics, comparison command, holdout discipline, and no-optimization boundary.
- [ ] Do not describe missed targets as achieved and do not add any Stage 5 scope.
- [ ] Commit `docs: record Stage 4 baseline and lock` only when the baseline is safe and the artifact is present.

### Task 10: Final verification, Draft PR, and hosted provider-free CI

**Files:**
- No implementation files beyond the completed tasks.

- [ ] Run `uv lock --check`, `uv sync --locked`, Ruff, format check, mypy, `make check`, `make eval-corpus-check`, `make eval-agent`, evaluation PostgreSQL tests, and `make eval-compare` against a deterministic self-copy for command mechanics.
- [ ] Run all existing Stage 3 permanent gates, `evaluation-contract`, `agent-acceptance`, `web-quality`, Docker build, and `git diff --check`.
- [ ] Verify the corpus SHA/counts, prompt, graph, five tools, LangGraph/LiteLLM pins, OpenAPI hash, seed fingerprint, both migration heads, and absence of Stage 3 source changes.
- [ ] Verify no provider secret appears in Git, baseline JSON/Markdown, logs, or PR body.
- [ ] Push `stage4/m4b-real-baseline`, open a Draft PR to `main`, wait for the fresh provider-free hosted CI run, and do not merge.
- [ ] Return the requested evidence packet including the execution SHA, baseline run ID, all metrics/category/split results, artifact paths, comparison proof, hosted job conclusions, and explicit single-agent/Stage-5 confirmations.
