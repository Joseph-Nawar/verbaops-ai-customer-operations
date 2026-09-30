# Stage 5 M5D-B DEV Results

**Status: PARTIAL - P0 completed and was scored; P1 stopped on its first public API HTTP 503. P2 and P3 were not run. The candidate sweep is incomplete, so no grounding candidate or model was selected. No production change was made.**

## Canonical provenance

- Benchmark: `rag-v0.2`, DEV only; 96 cases (72 answerable, 24 no-answer).
- Dataset SHA256: `398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595`.
- Knowledge manifest SHA256: `26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660`.
- Experiment-plan SHA256: `b9835dd0e7bb974480769d328f19d903cb9466828a0ac810200cc10b36251ba8`.
- PRE_EXPERIMENT_SHA: `347eccfd7aaa22332bdf36ee396715133b716b9c`.
- Canonical evaluated implementation SHA: `7f82c565e7f9fc085f2d81c2c04a9861444837a1`.
- Gate run: `canonical-gate-20260929T123626Z-45586c67` (identity SHA256 `3b75a4202803336b70b2c04c8eccf356b788391c5cf17d20370842bf5c5828b4`).
- P0 run: `canonical-M0-P0-20260929T124811Z-0d27c8d7` (identity SHA256 `02e58b8d147551130714ff754372c304a2ec4253295bd79365920ec5730ac546`).
- P1 run: `canonical-M0-P1-20260930T105712Z-c77394bd` (identity SHA256 `d79238b2a90b3b1cc1733c61f55632157a64268884d4ddb892deec0001ff182b`).
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

### P1_PROMPT_V3 - interrupted, not scored

P1 started as a fresh canonical run on the same pinned implementation and received **public API HTTP 503** on its first case, `m5d-v02-shipping-001`. It has 0/96 completed observations and no report. No retry, diagnostic request, smoke request, or further provider-backed call followed. The available current gateway log scan had no rate-limit marker or reset header; the cause of the 503 is therefore **unknown**, and it is not labeled as a confirmed quota failure.

### P2 and P3 - not run

P2 and P3 were not run after P1 stopped. No incomplete candidate was scored, and no P0 response was reused for another candidate. Since the candidate sweep is incomplete, there is no selection and no `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE` conclusion.

## Model and provider

M0 used `groq/openai/gpt-oss-120b` through LiteLLM capability alias `agent-fast`. The existing sanitized provider smoke from September 29 remains historical evidence; no new smoke or diagnostic request was made on September 30. Today, 66 new P0 benchmark cases completed and the first P1 case surfaced a public 503. The runner made no retry after that surfaced failure. The number of internal provider attempts behind the public API error is not established, and exact token consumption is not claimed. No credentials were persisted.

M1 (`Qwen/Qwen3-30B-A3B-Instruct-2507`) remains `M1_NOT_EXECUTED_LOCAL_RESOURCE_BLOCK`; no model was downloaded or substituted, and there is no model comparison.

Stage 4 DEV regression was not run because no grounding candidate qualified for the conditional regression. Release holdout was not executed; `selection.json` remains absent; production retrieval, prompt, model route, and Commerce tools are unchanged. M5D-C and Stage 6 have not begun.

## Historical/noncanonical evidence

Earlier gate and P0/P1 observations came from a dirty evaluation worktree; prior P2 observations span mixed implementation states. They remain excluded from the canonical gate and grounding evidence, all metrics above, and selection. The historical observations were not combined with these runs.

Machine-readable canonical summary: [m5d-b-dev-summary.json](../../evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json).
