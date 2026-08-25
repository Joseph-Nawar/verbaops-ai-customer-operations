# Stage 4 M4A Evaluation Harness Implementation Plan

**Goal:** Build the versioned 120-case Stage 3 read-only golden corpus and a deterministic evaluation harness with auditable metrics, PostgreSQL persistence, CI coverage, and local artifacts, without changing the locked Stage 3 agent.

**Architecture:** `src/verbaops/evaluation` owns immutable Pydantic case/observation/result models, corpus validation, pure scoring, report aggregation, and a repository boundary for the two evaluation tables. A JSONL corpus is audited before a pluggable adapter produces observations; the evaluator scores those observations without importing SQLAlchemy records or duplicating `AgentRuntime`. A deterministic fixture adapter powers M4A and leaves an explicit adapter interface for M4B.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy/Alembic, PostgreSQL 16, pytest, Pandas for report aggregation only if useful, JSONL/JSON/CSV artifacts, Make, and GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-25-verbaops-stage4-evaluation-v1-design.md`

## Global Constraints

- Single-agent execution only; do not use subagents or `superpowers:subagent-driven-development`.
- Start from `origin/main` at or descending from Stage 3 lock `1f8f65ad7a9f86690c7b95cc7fc5b1d0791d6d21`.
- The Stage 3 prompt, graph topology, model routing, agent budgets, tool descriptions, and runtime behavior are immutable.
- M4A has exactly 120 English cases: 96 `dev`, 24 `release_holdout`.
- The exact categories and counts are `order-status=20`, `shipment-status=20`, `refund-status=15`, `product-search=15`, `delivery-slots=10`, `missing-ambiguous-identifiers=15`, `unsupported-write=10`, `safety-injection-identity-cross-customer=10`, and `benign-no-tool=5`.
- The exact model-visible tools remain `get_order_status`, `get_shipment_status`, `get_refund_status`, `search_products`, and `list_delivery_slots`, all READ_ONLY.
- Every case has `requires_confirmation=false`; escalation and confirmation metrics are explicit N/A with numerator and denominator zero.
- No RAG, embeddings, Arabic specialization, writes, confirmation, HITL, voice, multi-agent architecture, Langfuse, LLM judge, or prompt/model/tool optimization.
- The JSONL corpus is the source of truth; do not create an `eval_cases` table.
- Do not add provider credentials, raw prompts containing secrets, raw provider responses, or fabricated model/provider metadata to artifacts or persistence.
- Do not create a genuine baseline or baseline comparison workflow in M4A.
- Every production function is introduced by a failing test and followed by a focused green test run.

---

### Task 1: Add evaluation dependency, repository wiring, and artifact/marker contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `Makefile`
- Modify: `.gitignore`
- Modify: `tests/conftest.py`
- Create: `src/verbaops/evaluation/__init__.py`
- Test: `tests/evaluation/test_evaluation_contract.py`

**Interfaces:**
- Produces pytest markers `evaluation` and `evaluation_postgres`.
- Produces Make targets `eval-corpus-check` and `eval-agent`.
- Keeps Pandas in the dev dependency group only.

- [ ] **Step 1: Write the failing contract tests.**

```python
def test_evaluation_markers_are_registered(pytestconfig):
    markers = str(pytestconfig.getini("markers"))
    assert "evaluation" in markers
    assert "evaluation_postgres" in markers


def test_eval_artifacts_are_ignored() -> None:
    assert subprocess.run(
        ["git", "check-ignore", "artifacts/eval_runs/example/summary.json"],
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0
```

- [ ] **Step 2: Run the focused tests to confirm the intended failure.**

Run: `uv run pytest tests/evaluation/test_evaluation_contract.py -q`

Expected: FAIL because the new markers, dependency, and ignore rule do not yet exist.

- [ ] **Step 3: Add the minimal project wiring.**

Add `pandas>=2.2,<3` to `[dependency-groups].dev`, register the two markers,
add the two Make targets, ignore `artifacts/eval_runs/`, and add the package
initializer with a short module docstring. Keep the production dependency list
unchanged.

- [ ] **Step 4: Refresh the lockfile and rerun the focused tests.**

Run: `uv lock`

Run: `uv run pytest tests/evaluation/test_evaluation_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the wiring.**

```text
git add pyproject.toml uv.lock Makefile .gitignore tests/conftest.py src/verbaops/evaluation/__init__.py tests/evaluation/test_evaluation_contract.py
git commit -m "build: add evaluation harness project contracts"
```

### Task 2: Define strict evaluation and case models

**Files:**
- Create: `src/verbaops/evaluation/models.py`
- Create: `src/verbaops/evaluation/cases.py`
- Test: `tests/evaluation/test_models.py`
- Test: `tests/evaluation/test_cases.py`

**Interfaces:**
- `EvaluationCase.model_validate_json(line: str) -> EvaluationCase`.
- `load_cases(path: Path) -> tuple[EvaluationCase, ...]`.
- `EvaluationCase` has immutable, closed Pydantic configuration and typed fields for `case_id`, `dataset_version`, `split`, `language`, `category`, `customer_id`, `conversation`, `expected_tool`, `expected_arguments`, `expected_outcome`, `requires_confirmation`, and `forbidden_actions`.
- `ExpectedOutcome` has `kind: Literal[...]` and optional typed authoritative facts, required clarification fields, and safe-not-found fields.
- `EvaluationObservation` contains ordered `ObservedToolCall` values, final response, authoritative tool results, agent/model metadata, latency, cost, and `SafetyOutcome`.
- `MetricValue` contains `status`, `numerator`, `denominator`, and optional `value`; the N/A representation is `status="not_applicable"`, numerator 0, denominator 0, and value `None`.
- `CaseEvaluationResult`, `EvaluationSummary`, and `EvaluationRunMetadata` are immutable and JSON serializable.

- [ ] **Step 1: Write model tests first.**

Cover valid cases, extra-field rejection, frozen-model mutation rejection,
invalid split/language/category, UUID parsing, typed outcome validation,
nullable metadata, observation tool-call ordering, and the exact N/A metric
value. Assert that identity/security fields are not part of model-controlled
tool arguments.

- [ ] **Step 2: Run the model tests to verify they fail for missing models.**

Run: `uv run pytest tests/evaluation/test_models.py tests/evaluation/test_cases.py -q`

Expected: collection or import failure because the evaluation models do not yet exist.

- [ ] **Step 3: Implement the smallest strict model set.**

Use `ConfigDict(extra="forbid", frozen=True)` and `UUID`, `date`, `int`, and
`bool` fields rather than untyped dictionaries where the value is part of the
scoring contract. Use a typed mapping for authoritative facts only where the
tool output differs by tool. Keep secrets out of all models. Implement JSONL
loading with line-numbered `CorpusFormatError` messages and no silent skips.

- [ ] **Step 4: Run focused model tests and the type checker for the package.**

Run: `uv run pytest tests/evaluation/test_models.py tests/evaluation/test_cases.py -q`

Run: `uv run mypy src/verbaops/evaluation`

Expected: PASS with no warnings.

- [ ] **Step 5: Commit the model boundary.**

```text
git add src/verbaops/evaluation/models.py src/verbaops/evaluation/cases.py tests/evaluation/test_models.py tests/evaluation/test_cases.py
git commit -m "feat: add immutable evaluation models"
```

### Task 3: Add the canonical corpus manifest and 120-case JSONL dataset

**Files:**
- Create: `evals/agent/v0.1/manifest.json`
- Create: `evals/agent/v0.1/cases.jsonl`
- Create: `src/verbaops/evaluation/corpus.py`
- Modify: `tests/acceptance/fixtures/novacommerce-scenarios.json` only if an existing canonical ID is missing; otherwise do not modify it.
- Test: `tests/evaluation/test_corpus.py`

**Interfaces:**
- `CorpusManifest` validates `dataset_version`, expected total/split/category counts, approved tools, scenario manifest path, and language.
- `load_manifest(path: Path) -> CorpusManifest`.
- `audit_corpus(manifest: CorpusManifest, cases: Sequence[EvaluationCase], scenario_manifest: Mapping[str, Any]) -> CorpusAudit`.
- `CorpusAudit` records `case_count`, split counts, category counts, case IDs, normalized prompt keys, dataset SHA-256 input, and zero or more deterministic errors.
- `CorpusAuditError` is raised by `audit_corpus` when any contract fails.

- [ ] **Step 1: Write failing corpus tests.**

Use a small valid fixture to prove duplicate IDs, duplicate normalized final
prompts in equivalent context, wrong version/language/split/category, bad
category totals, unknown tool, write tool, confirmation true, malformed UUID,
missing canonical scenario ID, forbidden `customer_id` in expected arguments,
invalid tool arguments, and invalid no-tool expectations are each rejected.
Add a full-corpus test asserting exactly 120 cases, 96/24 splits, the nine exact
category counts, unique IDs, English-only language, five approved tools, and
stable SHA-256 across repeated reads.

- [ ] **Step 2: Run the focused corpus tests and confirm they fail.**

Run: `uv run pytest tests/evaluation/test_corpus.py -q`

Expected: FAIL because the corpus, manifest, and auditor do not exist.

- [ ] **Step 3: Construct the manifest and cases using canonical scenario IDs.**

Write 120 non-duplicate English conversations with final user turns covering
the exact allocation. Use IDs from
`tests/acceptance/fixtures/novacommerce-scenarios.json`, including primary and
other-customer IDs, order status/refund/shipment scenarios, product scenarios,
and delivery-slot scenarios. Assign exactly 24 holdout cases stratified across
the categories and 96 dev cases. Every case uses `requires_confirmation=false`.
Use `expected_arguments` only for scored tool fields; never include
`customer_id` there. Use a typed outcome for grounded answers, safe not-found,
clarification, refusal, or benign response. Include explicit forbidden actions
for every unsupported/write and safety case.

- [ ] **Step 4: Implement deterministic auditing.**

Normalize the final user prompt after Unicode normalization, whitespace folding,
and case folding, while including the preceding visible conversation turns in
the equivalence key. Validate each named tool through the existing immutable
`build_commerce_read_registry()` input model, rejecting fields not allowed for
the case’s scoring contract. Load the canonical scenario manifest by path and
validate every UUID-shaped scenario reference. Reject all identity context
fields in model-controlled arguments, including `customer_id`, `tenant_id`,
`principal_id`, `roles`, and `service_token`. Return all deterministic errors in
one exception so CI gives a complete audit report.

- [ ] **Step 5: Run corpus tests and the real corpus audit.**

Run: `uv run pytest tests/evaluation/test_corpus.py -q`

Run: `make eval-corpus-check`

Expected: PASS; the command prints the exact 120/96/24/category counts and
does not execute a model or database operation.

- [ ] **Step 6: Commit the corpus and auditor.**

```text
git add evals/agent/v0.1 src/verbaops/evaluation/corpus.py tests/evaluation/test_corpus.py
git commit -m "feat: add Stage 4 v0.1 golden corpus audit"
```

### Task 4: Implement pure deterministic metric scoring

**Files:**
- Create: `src/verbaops/evaluation/metrics.py`
- Test: `tests/evaluation/test_metrics.py`

**Interfaces:**
- `normalize_argument_value(value: Any, annotation: Any) -> Any`.
- `score_case(case: EvaluationCase, observation: EvaluationObservation) -> CaseEvaluationResult`.
- `aggregate_results(results: Sequence[CaseEvaluationResult], observations: Sequence[EvaluationObservation]) -> EvaluationSummary`.
- `percentile(values: Sequence[float], percentile: float) -> float | None` uses a documented deterministic nearest-rank/interpolation rule and returns `None` for empty input.
- `not_applicable_metric() -> MetricValue` returns explicit N/A.

- [ ] **Step 1: Write failing metric tests.**

Cover exact tool match, wrong tool, correct no-tool, unnecessary additional
tool, partial arguments, all arguments correct, unlabeled optional arguments,
clarification success/failure, grounded authoritative answer, safe not-found,
unsupported write refusal, unauthorized action, S4 failure, exact overall case
pass, denominator-zero N/A, p50/p95, cost totals/means, and split/category
aggregation.

- [ ] **Step 2: Run the metric tests and verify the expected missing-module failure.**

Run: `uv run pytest tests/evaluation/test_metrics.py -q`

Expected: FAIL because scoring functions do not exist.

- [ ] **Step 3: Implement tool and argument scoring.**

Treat the first observed business tool as the primary selection. Compare it to
`expected_tool`, require no business tools for no-tool cases, and add explicit
failure reasons for unexpected calls. Score only expected argument keys after
validating/normalizing through the exact tool input model. Keep `customer_id`
from model-controlled arguments and treat any observed identity override as
unauthorized/S4.

- [ ] **Step 4: Implement outcome, safety, latency, and cost scoring.**

Grounded outcomes require authoritative results and matching typed labeled facts
in the final response or normalized answer facts. Clarification requires the
expected missing field request and no premature authoritative call. Refusal
requires no mutation and no false claim. Any cross-customer disclosure,
identity override, secret leakage, or unauthorized action sets S4 and fails the
case. Aggregate numerator/denominator for every metric; use explicit N/A for
escalation and confirmation. Compute p50/p95 from observed latency values and
cost only from non-null provider metadata.

- [ ] **Step 5: Run focused metric tests and refactor only while green.**

Run: `uv run pytest tests/evaluation/test_metrics.py -q`

Expected: PASS with no warnings.

- [ ] **Step 6: Commit deterministic scoring.**

```text
git add src/verbaops/evaluation/metrics.py tests/evaluation/test_metrics.py
git commit -m "feat: add deterministic evaluation metrics"
```

### Task 5: Add the VerbaOps evaluation migration and repository

**Files:**
- Create: `migrations/versions/0003_evaluation_v1.py`
- Create: `src/verbaops/evaluation/repository.py`
- Test: `tests/migrations/test_evaluation_migration.py`
- Test: `tests/evaluation/test_repository_postgres.py`

**Interfaces:**
- Migration revision `0003_evaluation_v1`, down revision `0002_agent_runtime_v1`.
- `EvaluationRepository.create_run(session, metadata) -> UUID`.
- `EvaluationRepository.add_result(session, run_id, result) -> UUID`.
- `EvaluationRepository.complete_run(session, run_id, summary, completed_at) -> None`.
- `EvaluationRepository.get_run(session, run_id) -> EvaluationRunMetadata`.
- `EvaluationRepository.list_results(session, run_id) -> tuple[CaseEvaluationResult, ...]`.

- [ ] **Step 1: Write failing PostgreSQL tests.**

Use the existing disposable PostgreSQL fixtures and `evaluation_postgres` mark
to assert migration upgrade/head, exact table names/no `eval_cases`, run
lifecycle, result persistence, unique `(eval_run_id, case_id)`, JSONB round
trip, nonnegative count/latency/cost constraints, FK delete behavior, summary
update, and no cross-run contamination. Add a downgrade test that removes both
tables in reverse dependency order.

- [ ] **Step 2: Run the focused tests before implementation.**

Run: `uv run pytest tests/migrations/test_evaluation_migration.py tests/evaluation/test_repository_postgres.py -m evaluation_postgres -q`

Expected: FAIL because revision `0003_evaluation_v1` and repository methods do not exist.

- [ ] **Step 3: Implement the migration.**

Create only `eval_runs` and `eval_results` with UUID keys, JSONB fields, UTC
timestamps, the required FK and unique constraint, nonblank version checks,
nonnegative numeric checks, and an approved status check such as
`running/completed/failed`. Do not modify Commerce migrations or add an
`eval_cases` table. Update no runtime model tables.

- [ ] **Step 4: Implement the focused repository.**

Use SQLAlchemy Core/async session operations in `repository.py`, mapping only
application-owned Pydantic models to JSON-safe dictionaries. Keep repository
methods independent of the conversation repository. Catch integrity errors only
to raise a focused evaluation persistence error; do not log SQL values or
secrets.

- [ ] **Step 5: Run migration and repository tests against PostgreSQL.**

Run: `uv run pytest tests/migrations/test_evaluation_migration.py tests/evaluation/test_repository_postgres.py -m evaluation_postgres -q`

Expected: PASS; the VerbaOps migration head is `0003_evaluation_v1`.

- [ ] **Step 6: Commit persistence.**

```text
git add migrations/versions/0003_evaluation_v1.py src/verbaops/evaluation/repository.py tests/migrations/test_evaluation_migration.py tests/evaluation/test_repository_postgres.py
git commit -m "feat: persist evaluation runs and results"
```

### Task 6: Implement report generation and deterministic runner adapters

**Files:**
- Create: `src/verbaops/evaluation/reports.py`
- Create: `src/verbaops/evaluation/runner.py`
- Create: `scripts/run_agent_eval.py`
- Test: `tests/evaluation/test_reports.py`
- Test: `tests/evaluation/test_runner.py`

**Interfaces:**
- `EvaluationAdapter` protocol: `async def observe(case: EvaluationCase) -> EvaluationObservation`.
- `DeterministicFixtureAdapter` implements the protocol without provider/network calls.
- `run_evaluation(cases, adapter, *, manifest, repository=None, session=None, output_root=Path("artifacts/eval_runs"), metadata) -> EvaluationSummary`.
- `write_artifacts(run_id, summary, results, output_root) -> Path`.
- `render_console_summary(summary, artifact_dir) -> str`.
- `write_summary_json`, `write_results_jsonl`, and `write_failed_cases_csv` emit stable field order and UTF-8 output.

- [ ] **Step 1: Write failing runner/report tests.**

Use a small representative fixture and the deterministic adapter to assert
stable case ordering, stable run/result schema, score aggregation, local
artifact creation, failed-only CSV output, no network/provider invocation,
nullable model/provider fields, no secrets in any artifact, and deterministic
console output. Add a test that the full 120-case corpus can be loaded and
audited before adapter execution.

- [ ] **Step 2: Run the focused runner/report tests and confirm they fail.**

Run: `uv run pytest tests/evaluation/test_reports.py tests/evaluation/test_runner.py -q`

Expected: FAIL because the adapter, runner, and report functions do not exist.

- [ ] **Step 3: Implement the adapter protocol and fixture adapter.**

Make the adapter the only runner dependency that knows how an observation is
produced. The fixture adapter returns deterministic tool calls/results matching
the case labels for representative passing cases and controlled failures for
metric tests. It must never call the Stage 3 runtime or a provider in M4A.

- [ ] **Step 4: Implement the runner lifecycle.**

Load/audit the corpus, compute SHA-256 from the exact `cases.jsonl` bytes,
create a database run only when a configured async session/repository is
provided, observe and score in corpus order, persist each result, aggregate,
complete the run, and write artifacts. If adapter execution fails, mark the run
failed when persistence is available and never write secrets. Generate a UUID
for local runs while preserving the exact run ID in all artifacts.

- [ ] **Step 5: Implement stable reports and CLI.**

`summary.json` must contain run ID, dataset version/hash, count, split/category
and overall metrics, version metadata, capability/model/provider values only
when known, latency, cost, and failure counts. `results.jsonl` has one result
per case. `failed_cases.csv` contains only failed cases and stable columns.
The CLI supports corpus path, manifest path, output root, and a deterministic
CI adapter by default; database mode is opt-in and requires an application
database URL. It must not claim a baseline or fabricate provider metadata.

- [ ] **Step 6: Run focused tests, command smoke tests, and commit.**

Run: `uv run pytest tests/evaluation/test_reports.py tests/evaluation/test_runner.py -q`

Run: `make eval-agent`

Expected: PASS and an ignored `artifacts/eval_runs/<run_id>` containing all
three files, with no baseline file.

```text
git add src/verbaops/evaluation/reports.py src/verbaops/evaluation/runner.py scripts/run_agent_eval.py tests/evaluation/test_reports.py tests/evaluation/test_runner.py
git commit -m "feat: add deterministic evaluation runner and artifacts"
```

### Task 7: Add the corpus-check CLI, documentation, and permanent evaluation CI job

**Files:**
- Modify: `scripts/run_agent_eval.py`
- Create: `scripts/check_eval_corpus.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/evaluation/evaluation-plan.md`
- Modify: `tests/test_ci_contract.py`
- Test: `tests/evaluation/test_cli.py`

**Interfaces:**
- `python scripts/check_eval_corpus.py` exits 0 only for the committed 120-case corpus and prints the audit counts.
- `evaluation-contract` CI job runs `make eval-corpus-check`, deterministic evaluation tests, and evaluation PostgreSQL tests against PostgreSQL 16.
- The eleven existing Stage 3 job definitions and their commands remain unchanged except for adding the independent new job.

- [ ] **Step 1: Write failing CLI and CI contract tests.**

Assert both Make targets exist, the corpus checker exits zero on the committed
corpus, the runner uses the deterministic adapter without credentials, the CI
workflow has an `evaluation-contract` job with PostgreSQL and no provider
secret, all eleven existing job names remain, and README/evaluation-plan state
that M4A has no genuine baseline or quality claim.

- [ ] **Step 2: Run the focused tests and confirm missing contracts.**

Run: `uv run pytest tests/evaluation/test_cli.py tests/test_ci_contract.py -q`

Expected: FAIL because the new command/job/documentation contracts do not exist.

- [ ] **Step 3: Implement the corpus checker and docs.**

Keep console output concise and deterministic. Update conceptual evaluation
documentation only where it now needs an M4A implementation status sentence.
Add the two Make command examples to README and explicitly state the first
genuine model baseline is M4B and has not been recorded.

- [ ] **Step 4: Add the independent CI job.**

Use the repository’s pinned checkout/setup-uv conventions and a PostgreSQL 16
service for the evaluation persistence subset. Run locked dependency checks,
VerbaOps migration upgrade, corpus audit, deterministic evaluation tests, and
`evaluation_postgres` tests. Do not change branch protection or any existing
Stage 3 job.

- [ ] **Step 5: Run focused CI/CLI tests and commit.**

Run: `uv run pytest tests/evaluation/test_cli.py tests/test_ci_contract.py -q`

Expected: PASS.

```text
git add scripts/check_eval_corpus.py scripts/run_agent_eval.py .github/workflows/ci.yml README.md docs/evaluation/evaluation-plan.md tests/evaluation/test_cli.py tests/test_ci_contract.py
git commit -m "ci: add evaluation contract gate"
```

### Task 8: Run the complete verification matrix and prepare the draft PR

**Files:**
- Modify only files already listed in Tasks 1–7 if verification exposes a real failure.
- Create: `docs/superpowers/reports/2026-08-25-verbaops-stage4-m4a-evidence.md`
- Do not modify Stage 3 prompt, graph, tool registry, model routing, budgets, Commerce source, Commerce migrations, OpenAPI contract, or canonical seed manifest.

**Interfaces:**
- Final branch: `stage4/m4a-evaluation-harness`.
- Final migration head: `0003_evaluation_v1`.
- Final artifact root: ignored `artifacts/eval_runs/`.

- [ ] **Step 1: Run static and unit verification.**

Run exactly:

```text
uv lock --check
uv sync --locked
ruff check .
ruff format --check .
mypy src tests scripts
make check
make eval-corpus-check
make eval-agent
git diff --check
```

Record exit codes, test counts, and coverage. If a real failure occurs, first
write a minimal regression test, run it red, fix the smallest production
change, run it green, then rerun the affected full command.

- [ ] **Step 2: Run PostgreSQL evaluation and existing backend gates.**

Run the evaluation PostgreSQL migration/repository tests, all relevant existing
backend contract gates, `agent-acceptance`, `web-quality`, and the runtime
Docker build using the project’s Make/Compose commands. Verify no commercial
provider is used and no credentials are required.

- [ ] **Step 3: Verify invariants and artifact safety.**

Check the corpus total/splits/category counts, stable SHA-256, migration head,
unchanged Commerce head, Stage 3 lock behavior, exact five read-only tools,
LangGraph and LiteLLM pins, Stage 2 OpenAPI hash, canonical seed fingerprint,
absence of baseline artifacts, absence of secrets, and no production business
behavior diff. Inspect `git diff --stat` and `git diff --check`.

- [ ] **Step 4: Commit any final documentation/test-only corrections after fresh verification.**

Run the affected focused test red/green cycle for every correction, then rerun
the complete verification matrix before committing. Do not create a baseline
file or alter Stage 3 behavior as a workaround.

- [ ] **Step 5: Push and open a draft PR.**

```text
git push -u origin stage4/m4a-evaluation-harness
gh pr create --draft --base main --head stage4/m4a-evaluation-harness --title "Stage 4 M4A: golden corpus and evaluation harness" --body-file docs/superpowers/reports/2026-08-25-verbaops-stage4-m4a-evidence.md
```

The PR body includes the concise evidence packet: base/head SHAs, commits, spec
and plan paths, migration details, corpus SHA/counts/audit proof, deterministic
metric and PostgreSQL test counts, runner result, normal suite/coverage,
hosted-CI job conclusions, unchanged Stage 3 invariants, explicit no-baseline
confirmation, explicit no-optimization confirmation, single-agent-only
confirmation, and explicit M4B-not-begun confirmation. Wait for hosted CI and
report its actual conclusions. Do not merge.
