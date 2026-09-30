# Stage 5 M5D-B DEV Results

**Status: PARTIAL.** P0 and P2 completed all 96 DEV cases and were scored; both fail the frozen grounding quality floors. P1 is execution-ineligible after a deterministic frozen agent-budget failure at 16/96. P3 stopped at 39/96 after a Groq HTTP 429 was correlated with its public API 503. P3 is incomplete and unscored, so the grounding sweep has no selection and no final no-candidate conclusion. No production change was made.

## Canonical provenance

- Benchmark: `rag-v0.2`, DEV only; 96 cases (72 answerable, 24 no-answer).
- Dataset SHA256: `398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595`.
- Knowledge manifest SHA256: `26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660`.
- Experiment-plan SHA256: `b9835dd0e7bb974480769d328f19d903cb9466828a0ac810200cc10b36251ba8`.
- PRE_EXPERIMENT_SHA: `347eccfd7aaa22332bdf36ee396715133b716b9c`.
- Application under test: `7f82c565e7f9fc085f2d81c2c04a9861444837a1`.
- Evaluation-harness correction commit: `86c81196e7ed4c967eec62bfc2cab9484820529c` (hosted CI run `36741222331`, all jobs successful).
- Gate run: `canonical-gate-20260929T123626Z-45586c67` (identity SHA256 `3b75a4202803336b70b2c04c8eccf356b788391c5cf17d20370842bf5c5828b4`).
- P0 run: `canonical-M0-P0-20260929T124811Z-0d27c8d7` (corrected identity SHA256 `0d464fd5a80c2081b63d96fa7d96a49d87bb1e23c4ef9aa690705f6db7d959f6`).
- P1 run: `canonical-M0-P1-20260930T105712Z-c77394bd` (corrected identity SHA256 `68364c40b7e713bbc1c14a98396f07ab652ad85252275a82897371df45da4bc4`).
- P2 run: `canonical-M0-P2-20260930T135336Z-7c951350` (corrected identity SHA256 `47c71abfc793ea6ebaa54a44e2354b6f3908e1902b86a32f3c2f888917397c16`).
- P3 run: `canonical-M0-P3-20260930T165735Z-277d35de` (identity SHA256 `fd64df4648ec046709b2629f92ffee4219da65fa1d5a4cc6beadcb967fa503bf`).
- All grounding-run identities distinguish the application SHA from evaluation-harness SHA. Their artifacts and hashes are bound by [dev-decision.json](../../evals/rag/v0.2/dev-decision.json) and [m5d-b-dev-summary.json](../../evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json).

## Evaluation-harness provenance correction

The runner duplicated version-selection logic instead of deriving identity from the actual `AgentEvaluationProfile`. At application SHA `7f82c565…`, runtime profiles use prompt v2 only for P0 and prompt v3 for P1, P2, and P3; every evaluation profile uses graph `text-agent-m5d-v1`. The old runner assigned P2 prompt v2 and recorded the production/default graph v2 for every candidate.

The correction makes the runner and public API use the same `build_agent_evaluation_profile()` factory. The harness SHA is recorded separately from the fixed application-under-test SHA. A canonical-revision check rejects behavior/specification changes outside approved evaluation, provenance, test, documentation, and evidence paths. Agent runtime, graph, prompts, tools, retrieval, Commerce behavior, production model routing, and runtime budgets were not changed.

Persisted application-owned traces verified each completed migrated observation before its identity was changed:

| Candidate | Traces | Runtime prompt / graph | Old identity SHA256 | Corrected identity SHA256 | Non-provenance observation content |
| --- | ---: | --- | --- | --- | --- |
| P0 | 96 | `text-agent-system-v2` / `text-agent-m5d-v1` | `02e58b8d147551130714ff754372c304a2ec4253295bd79365920ec5730ac546` | `0d464fd5a80c2081b63d96fa7d96a49d87bb1e23c4ef9aa690705f6db7d959f6` | SHA256 unchanged: `8ed412f74daaafda5f7e37cb3856fd31f87e8c3ae2f955017e282c0c46e25ecc` |
| P1 | 16 | `text-agent-system-v3` / `text-agent-m5d-v1` | `d79238b2a90b3b1cc1733c61f55632157a64268884d4ddb892deec0001ff182b` | `68364c40b7e713bbc1c14a98396f07ab652ad85252275a82897371df45da4bc4` | SHA256 unchanged: `584aa36aafd1848cafef3927b159d3d901b1d3d0dfa2cb5261ac63f568051664` |
| P2 | 32 at migration | `text-agent-system-v3` / `text-agent-m5d-v1` | `79b499049690baecf8bffcc49c1af1a64de00161828a29bce50d1792c899c772` | `47c71abfc793ea6ebaa54a44e2354b6f3908e1902b86a32f3c2f888917397c16` | SHA256 unchanged: `7f754b676af6a1790e1c25d6c9375688e5352ed8ec77d39cdc137803dc9f057a` |

Each run’s `provenance-correction.json` retains the old identity, corrected identity, trace evidence, checkpoint hashes at migration, and before/after observation-content hash. P0’s report metrics compare exactly to the pre-migration committed report; only its identity field changed. P2’s first 32 observations still match the migration-time non-provenance content hash after the continuation. P1 was neither retried nor scored.

## Evidence-gate calibration

Each candidate used its own calibrated score scale. Eligibility required at least 90% no-answer rejection. Selection then maximized answerable acceptance, following the frozen tie rules.

| Candidate | Threshold | Answerable accepted | No-answer rejected | Total p95 |
| --- | ---: | ---: | ---: | ---: |
| G0_CURRENT_RRF | 0.029642545771578 | 13/72 (18.06%) | 24/24 (100.00%) | 166.52 ms |
| G1_DENSE_SIMILARITY | 0.857316698845967 | 40/72 (55.56%) | 22/24 (91.67%) | 174.94 ms |
| G2_TOP_EVIDENCE_CROSS_ENCODER | 0.2554669 | 56/72 (77.78%) | 22/24 (91.67%) | 371.42 ms |

The canonical DEV selector chose **`G2_TOP_EVIDENCE_CROSS_ENCODER` at `0.2554669`**. This DEV-only result did not alter production retrieval and did not open release holdout.

## Grounding candidates

The frozen quality floors are citation precision >=95%, labeled groundedness >=90%, unsupported recognized-fact rate <=10%, and expected-fact coverage >=70%. Only complete candidates were scored.

### P0_CURRENT - complete, quality-ineligible

P0 remains 96/96. Its metrics are identical to the pre-correction report:

| Metric | Result | Preregistered floor | Outcome |
| --- | ---: | ---: | --- |
| Citation precision | 12/18 = **66.67%** | >=95% | Fail |
| Labeled groundedness | 2/4 = **50.00%** | >=90% | Fail |
| Unsupported recognized factual units | 2/4 = **50.00%** | <=10% | Fail |
| Expected-fact coverage | 4/72 = **5.56%** | >=70% | Fail |
| Answer latency p50 / p95 | **1,601.04 / 9,938.39 ms** | n/a | Recorded |
| Cost metadata coverage | **96/96 (100%)** | n/a | Complete |
| Total / mean cost | **$0.02739015 / $0.0002853141** | n/a | 96 observations |
| Retrieval evidence-gate accuracy | **78/96 = 81.25%** | n/a | Recorded |

### P1_PROMPT_V3 - execution-ineligible at 16/96, not scored

P1 remains at 16/96 and was not retried. The blocked case `m5d-v02-returns-007` failed with `agent_budget_exceeded` after four successful model calls and three successful `search_products` tool calls; the frozen runtime blocked a fifth model call. Its scoring status is `NOT_SCORED_INCOMPLETE_EXECUTION`. No P1 `report.json` exists. The earlier HTTP 503/tool-use failure is retained as historical evidence and is not attributed as the cause of the later budget failure.

The execution-eligibility interpretation was introduced after observing this deterministic P1 runtime failure; it was not preregistered and is not a new quality threshold. The interpretation excludes candidates that cannot complete under the frozen runtime, without retrying deterministic agent/runtime failures. No frozen quality floor or tie rule changed.

### P2_FAIL_CLOSED_CITATIONS - complete, quality-ineligible

P2 resumed its existing 32/96 checkpoint after provenance correction and completed 64 new cases, reaching 96/96 with the same run ID and corrected identity. Its earlier `ReadTimeout`/Docker-WSL interruption is retained as historical evidence.

| Metric | Result | Preregistered floor | Outcome |
| --- | ---: | ---: | --- |
| Citation precision | 48/71 = **67.61%** | >=95% | Fail |
| Labeled groundedness | 0/0; undefined | >=90% | Fail: no recognized labeled units |
| Unsupported recognized-fact rate | Undefined | <=10% | Fail: denominator unavailable |
| Expected-fact coverage | 0/72 = **0.00%** | >=70% | Fail |
| Answer latency p50 / p95 | **1,410.9965 / 3,617.5875 ms** | n/a | Recorded |
| Cost metadata coverage | **96/96 (100%)** | n/a | Complete |
| Total / mean cost | **$0.0238044 / $0.0002479625** | n/a | 96 observations |
| Retrieval evidence-gate accuracy | **78/96 = 81.25%** | n/a | Recorded |

### P3_ONE_REPAIR_THEN_FAIL_CLOSED - provider-blocked at 39/96, not scored

P3 recorded 39 observations. `m5d-v02-payments-004` produced no observation; the public API returned HTTP 503. The application trace records `llm_unavailable`. In the same request window, LiteLLM logged Groq `RateLimitError` / `rate_limit_exceeded` and HTTP 429 for the configured M0 route. This is classified as a provider rate-limit interruption, not a deterministic application-behavior failure. No retry followed, no P3 report was generated, and no partial P3 metrics were calculated.

The available logs contained no `retry-after` or `x-ratelimit-*` headers, so the quota dimension and reset are **unknown**. A gateway request ID was not persisted on the failed application model-call trace; the classification is based on the tightly correlated timestamp and matching provider/model route. Gateway-internal retry count remains unknown. Provider-backed execution stopped after this surfaced 429.

## Grounding decision

P0 and P2 completed but failed the frozen quality floors. P1 is execution-ineligible because of the frozen application model-call budget. P3 is incomplete because of the correlated provider 429. Therefore no candidate is selected, and the sweep is **not complete enough to claim** `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE`; P3 has no scored result. No incomplete candidate was scored.

## Model and provider

M0 remained `groq/openai/gpt-oss-120b` through LiteLLM capability alias `agent-fast`. Across the recorded M5D-B execution, 185 benchmark cases completed and 188 public application case requests were made, including three requests that produced no observation. P2 added 64 completed cases; P3 added 39 completed cases and one provider-blocked request. Runner retries after surfaced failures were zero. No smoke or diagnostic request was made during these continuations. Provider-internal retry count and exact token consumption are unknown. New cases used 20-second inter-case pacing, excluded from answer-latency measurements. Credential scans of the new artifacts and gateway logs found no key.

M1 (`Qwen/Qwen3-30B-A3B-Instruct-2507`) remains `M1_NOT_EXECUTED_LOCAL_RESOURCE_BLOCK`; no model was downloaded or substituted, and there is no model comparison. Stage 4 DEV regression was not run because no completed grounding candidate qualified.

Release holdout was not executed; `selection.json` remains absent. Production retrieval, prompt, model route, Commerce tools, and runtime budgets are unchanged. M5D-C and Stage 6 have not begun.

## Historical/noncanonical evidence

Earlier gate and grounding observations from dirty or mixed implementation states remain excluded from canonical evidence and selection. The provenance correction changes only identity fields where every recorded observation’s application-owned trace proved the actual runtime prompt and graph versions. It does not combine or rescore noncanonical observations.

Machine-readable canonical summary: [m5d-b-dev-summary.json](../../evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json).
