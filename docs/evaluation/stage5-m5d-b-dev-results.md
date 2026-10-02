# Stage 5 M5D-B DEV Results

**Final status: `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE`.** P0, P2, and P3 completed all 96 DEV cases and were scored; each fails at least one frozen grounding quality floor. P1 is execution-ineligible after a deterministic frozen agent-budget failure at 16/96. P4 is execution-ineligible after a deterministic Groq response-format/tool-calling protocol incompatibility at 1/96. P5 is execution-ineligible after a Groq `tool_use_failed` at 2/96. P4 and P5 were not scored. No production change was made.

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

### P3_ONE_REPAIR_THEN_FAIL_CLOSED - complete, quality-ineligible

P3 resumed the existing run from 39/96 and completed 57 new DEV cases, reaching 96/96 with the same run ID and identity. The previously provider-blocked case `m5d-v02-payments-004` completed during this continuation. The earlier public HTTP 503 correlated with Groq HTTP 429 remains in the historical interruption artifacts; no retry followed that surfaced failure. On October 1, the user confirmed the daily quota window had reset. The continuation used 20-second inter-case pacing and made no separate smoke or diagnostic requests. No provider rate limit, public 503, or deterministic application failure occurred during the continuation.

| Metric | Result | Preregistered floor | Outcome |
| --- | ---: | ---: | --- |
| Citation precision | 50/79 = **63.29%** | >=95% | Fail |
| Labeled groundedness | 1/1 = **100.00%** | >=90% | Pass; only one recognized labeled unit |
| Unsupported recognized factual-unit rate | 0/1 = **0.00%** | <=10% | Pass; limited to recognized labeled units |
| Expected-fact coverage | 1/72 = **1.39%** | >=70% | Fail |
| Accepted-evidence citation compliance | 52/58 = **89.66%** | n/a | Recorded |
| Safe fallback count / rate | 6/96 = **6.25%** | n/a | Recorded |
| Repair attempts / successes / failures | **9 / 3 / 6** | n/a | Recorded |
| Answer latency p50 / p95 | **1,321.8 / 3,602.73 ms** | n/a | Recorded |
| Repair model latency p50 / p95 | **1,361.23 / 2,337.75 ms** | n/a | Recorded |
| Cost metadata coverage | **96/96 (100%)** | n/a | Complete |
| Total / mean cost | **$0.02634765 / $0.0002744547** | n/a | 96 observations |
| Repair cost total / mean | **$0.00308235 / $0.0003424833** | n/a | 9 costed repair attempts |
| Retrieval evidence-gate accuracy | **78/96 = 81.25%** | n/a | Recorded |
| Model metadata coverage | **96/96** | n/a | `groq/openai/gpt-oss-120b` via `agent-fast`; provider metadata field was empty |

P3 fails citation precision and expected-fact coverage, so it is quality-ineligible. Labeled groundedness counts benchmark-labeled factual units and does not detect every possible novel hallucinated claim; the 1/1 denominator is also small.

## Grounding decision

The final result is **`NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE`**. P0 and P2 completed but failed frozen quality floors; P1 is execution-ineligible at 16/96 and remains unscored; P3 completed but failed citation precision and expected-fact coverage. No candidate was selected, and incomplete P1 was not numerically evaluated against unavailable metrics.

| Candidate | Execution status | Scoring / quality result |
| --- | --- | --- |
| P0_CURRENT | Complete, execution-eligible | `QUALITY_INELIGIBLE` |
| P1_PROMPT_V3 | `EXECUTION_INELIGIBLE_AGENT_BUDGET_EXCEEDED`, 16/96 | `NOT_SCORED_INCOMPLETE_EXECUTION` |
| P2_FAIL_CLOSED_CITATIONS | Complete, execution-eligible | `QUALITY_INELIGIBLE` |
| P3_ONE_REPAIR_THEN_FAIL_CLOSED | Complete, execution-eligible | `QUALITY_INELIGIBLE` |
| P4_EVIDENCE_LINKED_SINGLE_PASS | `P4_EXECUTION_INELIGIBLE_GROQ_RESPONSE_FORMAT_TOOL_CALLING_INCOMPATIBILITY`, 1/96 | `NOT_SCORED_INCOMPLETE_EXECUTION` |
| P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS | `P5_EXECUTION_INELIGIBLE_GROQ_TOOL_USE_FAILED`, 2/96 | `NOT_SCORED_INCOMPLETE_EXECUTION` |

The execution-eligibility interpretation was introduced after observing the deterministic P1 runtime failure; it was not preregistered as an additional quality metric. No frozen quality floor or tie rule changed. Stage 4 DEV regression was not run because no grounding candidate qualified. P4 is not eligible for Stage 4 DEV or M5D-C.

## P4 canonical execution closeout

The provider-free implementation freeze was `77d04cd54143bd13b851ee2cbbe1f57766371fd0` (application-under-test and evaluation-harness SHA), with hosted CI run `36897816684` successful on that exact head. The single canonical run was `canonical-M0-P4-20261001T173102Z-31113cc8` (identity SHA256 `4a041a8f5966715dce3461064f4e964f5efb55162c06e283128cb5ecb0031647`) using the frozen G2 gate and threshold `0.2554669`.

The run made two public API case requests and retained one observation, `m5d-v02-shipping-001` of 96. It stopped on `m5d-v02-shipping-002`: the public API returned HTTP 503 and the captured LiteLLM/Groq error was HTTP 400, `invalid_request_error`, parameter `response_format`, with message `json mode cannot be combined with tool/function calling`. This is a deterministic provider/protocol incompatibility, not a grounding quality failure or rate-limit event. No retry was made. Provider-internal request/retry count is unknown. The one recorded case did not enter P4 extractive mode and is retained as canonical execution evidence, not representative quality evidence.

P4 is `P4_EXECUTION_INELIGIBLE_GROQ_RESPONSE_FORMAT_TOOL_CALLING_INCOMPATIBILITY`, incomplete and unscored. No partial quality metrics were calculated; this run provides no conclusion about whether P4 would pass any of the four grounding floors. No `report.json` was generated. The sanitized machine-readable closeout is [p4-closeout.json](../../evals/rag/v0.2/dev-evidence/canonical/canonical-M0-P4-20261001T173102Z-31113cc8/p4-closeout.json). The P4 plan SHA256 is `2645e6430f7b936ecda089589213b2cb9828fdc4b23c526d885ff9c353617eee`; this is the separately frozen P4 plan and does not replace the historical P0-P3 plan provenance above.

## P5 canonical execution closeout

The provider-free implementation freeze, application-under-test SHA, and evaluation-harness SHA remained `16fac0f5d416961eea7858a7fd54f220bfef3b32`; hosted CI run `36984148887` succeeded on that exact freeze. Canonical P5 inference occurred afterward without changing that freeze. The run was `canonical-M0-P5-20261002T085922Z-80872fc6`, identity SHA256 `62c95ac2e893cdab7aaf3f076e6599610d0e15f5a4f1725f10b283cdd52dd58f`, under P5 plan SHA256 `e700ec31f157f47837489fc2d26e1296388405f447701286adc899d7b42fc20e`.

P5 retained two of 96 observations (`m5d-v02-shipping-001` and `m5d-v02-shipping-002`) and stopped at `m5d-v02-shipping-003`. The public API returned HTTP 503; timestamp-correlated upstream Groq evidence recorded HTTP 400, `invalid_request_error`, code `tool_use_failed`, and a `failed_generation` field. The failed generation content was not persisted; the error parameter is unknown. No rate-limit marker was established and the benchmark runner did not retry. Provider/LiteLLM internal retry count is unknown. This records one generated tool-call rejection in this canonical request; it does not establish that Groq is generally unable to support local tool calls.

P5 is permanently classified `P5_EXECUTION_INELIGIBLE_GROQ_TOOL_USE_FAILED`. It is incomplete and unscored; no partial metrics or quality-floor conclusion were produced. The two observations remain canonical evidence but are not representative quality evidence. No `report.json` or selection was generated. The sanitized diagnosis is [p5-closeout.json](../../evals/rag/v0.2/dev-evidence/canonical/canonical-M0-P5-20261002T085922Z-80872fc6/p5-closeout.json). The P5 run cannot resume and no second P5 canonical run is permitted.

## Final M5D-B2 state

P0, P2, and P3 are execution-eligible but quality-ineligible. P1, P4, and P5 are execution-ineligible and unscored. Therefore the final decision is `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE`; no candidate was selected or promoted. Canonical evidence status is `COMPLETE` because the evidence needed to establish P5's terminal execution-ineligible outcome is complete, even though P5 itself is only 2/96. M5D-C remains blocked and was not entered. Stage 4 DEV was not run for P4 or P5. Release holdout remains untouched, `selection.json` remains absent, and there is no further grounding candidate in M5D-B2.

## Model and provider

M0 remained `groq/openai/gpt-oss-120b` through LiteLLM capability alias `agent-fast`. On October 1, the P3 continuation completed 57 new cases (57 public application case requests) using 20-second inter-case pacing. There were zero surfaced provider 429/503 events, zero failed application requests, zero runner retries after a surfaced failure, and zero diagnostic or smoke requests. The previous September 30 session counters remain recorded separately in the machine-readable decision: 185 completed benchmark cases, 188 public application case requests, and three requests that produced no observation. Provider-internal retry counts and exact token consumption are unknown. Credential scans found no key in the new artifacts or logs.

M1 (`Qwen/Qwen3-30B-A3B-Instruct-2507`) remains `M1_NOT_EXECUTED_LOCAL_RESOURCE_BLOCK`; no model was downloaded or substituted, and there is no model comparison. Stage 4 DEV regression was not run because no completed grounding candidate qualified.

Release holdout was not executed; `selection.json` remains absent. Production retrieval, prompt, model route, Commerce tools, and runtime budgets are unchanged. M5D-C and Stage 6 have not begun.

## Historical/noncanonical evidence

Earlier gate and grounding observations from dirty or mixed implementation states remain excluded from canonical evidence and selection. The provenance correction changes only identity fields where every recorded observation’s application-owned trace proved the actual runtime prompt and graph versions. It does not combine or rescore noncanonical observations.

Machine-readable canonical summary: [m5d-b-dev-summary.json](../../evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json).
