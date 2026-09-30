# Stage 5 M5D-B DEV Results

**Status: PARTIAL - P0 completed and was scored; P1 has 16/96 observations and is unscored after a public API HTTP 502 at the pinned application model-call budget. P2 and P3 were not run. The candidate sweep is incomplete, so no grounding candidate or model was selected. No production change was made.**

## Canonical provenance

- Benchmark: `rag-v0.2`, DEV only; 96 cases (72 answerable, 24 no-answer).
- Dataset SHA256: `398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595`.
- Knowledge manifest SHA256: `26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660`.
- Experiment-plan SHA256: `b9835dd0e7bb974480769d328f19d903cb9466828a0ac810200cc10b36251ba8`.
- PRE_EXPERIMENT_SHA: `347eccfd7aaa22332bdf36ee396715133b716b9c`.
- Canonical evaluated implementation SHA: `7f82c565e7f9fc085f2d81c2c04a9861444837a1`.
- Gate run: `canonical-gate-20260929T123626Z-45586c67` (identity SHA256 `3b75a4202803336b70b2c04c8eccf356b788391c5cf17d20370842bf5c5828b4`).
- P0 run: `canonical-M0-P0-20260929T124811Z-0d27c8d7` (identity SHA256 `02e58b8d147551130714ff754372c304a2ec4253295bd79365920ec5730ac546`).
- P1 run: `canonical-M0-P1-20260930T105712Z-c77394bd` (identity SHA256 `d79238b2a90b3b1cc1733c61f55632157a64268884d4ddb892deec0001ff182b`), currently 16/96 observations.
- P0 and P1 artifacts are under [canonical DEV evidence](../../evals/rag/v0.2/dev-evidence/canonical/). The decision and summary bind relative artifact paths and SHA256 values in [dev-decision.json](../../evals/rag/v0.2/dev-decision.json) and [m5d-b-dev-summary.json](../../evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json).

The gate run completed all 96 DEV cases on the clean committed implementation. It retained frozen hybrid RRF ranking and the same final five evidence candidates; only the preregistered evaluation confidence signal varied by gate.

## Evidence-gate calibration

Each candidate used its own calibrated score scale. Eligibility required at least 90% no-answer rejection. Selection then maximized answerable acceptance, following the frozen tie rules.

| Candidate | Threshold | Answerable accepted | No-answer rejected | Total p95 |
| --- | ---: | ---: | ---: | ---: |
| G0_CURRENT_RRF | 0.029642545771578 | 13/72 (18.06%) | 24/24 (100.00%) | 166.52 ms |
| G1_DENSE_SIMILARITY | 0.857316698845967 | 40/72 (55.56%) | 22/24 (91.67%) | 174.94 ms |
| G2_TOP_EVIDENCE_CROSS_ENCODER | 0.2554669 | 56/72 (77.78%) | 22/24 (91.67%) | 371.42 ms |

The canonical DEV selector chose **`G2_TOP_EVIDENCE_CROSS_ENCODER` at `0.2554669`**: 56/72 answerable cases accepted (77.78%) and 22/24 no-answer cases rejected (91.67%). This met the preregistered 70% answerable-acceptance goal and mandatory 90% no-answer-rejection guard. It is a DEV-only gate result; it did not change or promote the production profile and did not open release holdout.

## Grounding candidates

### P0_CURRENT - complete, scored

P0 resumed the existing identity-bound run and completed the remaining 66 cases with **20-second inter-case pacing**, excluded from answer-latency measurements. Its checkpoint now has exactly 96 unique expected DEV case IDs. The pinned implementation, candidate, gate, threshold, dataset, and run identity remained unchanged. The old `interruption.json` is retained as a record of the previous 30/96 interruption; the resumed run's current completion is recorded by its 96-case metadata and report.

| Metric | Result | Preregistered floor | Outcome |
| --- | ---: | ---: | --- |
| Citation precision | 12/18 = **66.67%** | >=95% | Fail |
| Labeled groundedness | 2/4 = **50.00%** | >=90% | Fail |
| Unsupported recognized factual units | 2/4 = **50.00%** | <=10% | Fail |
| Expected-fact coverage | 4/72 = **5.56%** | >=70% | Fail |
| Answer latency p50 / p95 | **1,601.04 / 9,938.39 ms** | n/a | Recorded |
| Cost metadata coverage | **96/96 (100%)** | n/a | Complete |
| Total / mean cost over costed observations | **$0.02739015 / $0.0002853141** | n/a | 96 observations |
| Retrieval evidence-gate accuracy | **78/96 = 81.25%** | n/a | Recorded |

P0 is complete and scoreable, but it fails each listed grounding quality floor. The report's cost total and mean cover all 96 observations because cost metadata coverage is 96/96. Model metadata was present in 96/96 observations: model `groq/openai/gpt-oss-120b`, alias `agent-fast`. The provider field was not populated in model metadata, so Groq is identified as the configured provider family.

### P1_PROMPT_V3 - interrupted at 16/96, not scored

P1 resumed the existing run and identity; no new run was created. The initial request for `m5d-v02-shipping-001` surfaced as public HTTP 503 and recorded no observation. The retained LiteLLM trace shows the upstream returned HTTP 400 `invalid_request_error` / `tool_use_failed`: a generated tool name included a commentary-channel marker appended to `search_products`, which did not match the declared tool. There was no 429 or rate-limit evidence. The trace establishes this proximate response, but not why the model emitted the malformed tool name, so the initial 503 is classified **D - unknown underlying cause**. Because P1 still had zero observations and the daily quota was known to have reset, one continuation of this same run was allowed; the first case then completed and was recorded.

The continuation completed 16 unique expected DEV cases under the unchanged identity and stopped on `m5d-v02-returns-007` with public HTTP 502. The persisted application trace for that case records `agent_budget_exceeded`; all four model calls and all three `search_products` tool calls succeeded. The pinned runtime permits at most four model calls and raises the budget error before a fifth call; the public API maps that error to HTTP 502. Gateway access logs for the correlated window contain 275 HTTP 200 entries, with no 429, 5xx, retry-after, or x-ratelimit marker. This latest stop is classified **B - application agent-budget stop**, not a provider rate limit or upstream 5xx. No retry followed it.

The P1 run remains **16/96 and unscored**. It has no `report.json`; its checkpoint, unchanged identity sidecar, latest interruption, metadata, run summary, and sanitized failure diagnosis are listed with SHA256 values in [dev-decision.json](../../evals/rag/v0.2/dev-decision.json). The diagnosis artifact is [failure-diagnosis.json](../../evals/rag/v0.2/dev-evidence/canonical/canonical-M0-P1-20260930T105712Z-c77394bd/failure-diagnosis.json). No metrics were computed from these partial observations.

### P2 and P3 - not run

P2 and P3 were not run after P1 stopped. No incomplete candidate was scored, and no P0 response was reused for another candidate. Since the candidate sweep is incomplete, there is no selection and no `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE` conclusion.

## Model and provider

M0 remained `groq/openai/gpt-oss-120b` through LiteLLM capability alias `agent-fast`. Today, 66 new P0 observations and 16 P1 observations completed. Two public application requests failed without producing benchmark observations: the initial P1 HTTP 503 and the later P1 HTTP 502. One operational continuation was made after the first P1 request had produced no observation. There were no runner retries after the latest surfaced failure, no diagnostic or smoke requests, and no additional provider request after the HTTP 502. The provider's internal retry count and exact token consumption are unknown. New cases used 20-second inter-case pacing, excluded from answer-latency measurements. No credentials were persisted.

M1 (`Qwen/Qwen3-30B-A3B-Instruct-2507`) remains `M1_NOT_EXECUTED_LOCAL_RESOURCE_BLOCK`; no model was downloaded or substituted, and there is no model comparison.

Stage 4 DEV regression was not run because no completed grounding candidate qualified. Release holdout was not executed; `selection.json` remains absent; production retrieval, prompt, model route, and Commerce tools are unchanged. M5D-C and Stage 6 have not begun.

## Historical/noncanonical evidence

Earlier gate and P0/P1 observations came from a dirty evaluation worktree; prior P2 observations span mixed implementation states. They remain excluded from the canonical gate and grounding evidence, all metrics above, and selection. The historical observations were not combined with these runs.

Machine-readable canonical summary: [m5d-b-dev-summary.json](../../evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json).
