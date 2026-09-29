# Stage 5 M5D-B DEV Results

**Status: PARTIAL ? canonical grounding evaluation stopped during P0 after a provider rate limit. No grounding candidate or model was selected, and no production change was made.**

## Canonical provenance

- Benchmark: `rag-v0.2`, DEV only; 96 cases (72 answerable, 24 no-answer).
- Dataset SHA256: `398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595`.
- Knowledge manifest SHA256: `26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660`.
- Experiment-plan SHA256: `b9835dd0e7bb974480769d328f19d903cb9466828a0ac810200cc10b36251ba8`.
- PRE_EXPERIMENT_SHA: `347eccfd7aaa22332bdf36ee396715133b716b9c`.
- Canonical evaluated implementation SHA: `7f82c565e7f9fc085f2d81c2c04a9861444837a1`.
- Gate run ID: `canonical-gate-20260929T123626Z-45586c67`; grounding run ID: `canonical-M0-P0-20260929T124811Z-0d27c8d7`.
- Canonical outputs are under [canonical DEV evidence](../../evals/rag/v0.2/dev-evidence/canonical/). The run identities and per-artifact SHA256 values are bound in [dev-decision.json](../../evals/rag/v0.2/dev-decision.json) and [m5d-b-dev-summary.json](../../evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json).

The canonical evidence-gate run completed all 96 DEV cases on the clean committed implementation. It retained the frozen hybrid RRF ranking and final five evidence candidates; only the preregistered evaluation confidence signal varied by gate.

## Evidence-gate calibration

Each candidate used its own calibrated score scale. Eligibility required at least 90% no-answer rejection. Selection then maximized answerable acceptance, following the frozen tie rules.

| Candidate | Threshold | Answerable accepted | No-answer rejected | Total p95 |
| --- | ---: | ---: | ---: | ---: |
| G0_CURRENT_RRF | 0.029642545771578 | 13/72 (18.06%) | 24/24 (100.00%) | 166.52 ms |
| G1_DENSE_SIMILARITY | 0.857316698845967 | 40/72 (55.56%) | 22/24 (91.67%) | 174.94 ms |
| G2_TOP_EVIDENCE_CROSS_ENCODER | 0.2554669 | 56/72 (77.78%) | 22/24 (91.67%) | 371.42 ms |

The canonical DEV selector chose **`G2_TOP_EVIDENCE_CROSS_ENCODER` at `0.2554669`**: 56/72 answerable cases accepted (77.78%) and 22/24 no-answer cases rejected (91.67%). This meets the preregistered 70% answerable-acceptance goal and mandatory 90% no-answer-rejection guard. It is a DEV-only gate result; it did not change or promote the production profile and did not open release holdout.

## Grounding candidates

P0 began through the real public Stage 5 API with M0 and the selected G2 gate. It stopped after **18/96** completed cases when case `m5d-v02-returns-009` returned public API HTTP 503; gateway logs contained provider HTTP 429 rate-limit events. The run was preserved as `canonical-M0-P0-20260929T124811Z-0d27c8d7`. The partial P0 observations were **not scored** and are not used for candidate eligibility.

P1, P2, and P3 were not run in the canonical sweep. No retry was made after the rate limit, no grounding candidate was selected, and no `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE` conclusion is claimed because the required candidate set did not complete.

## Model and provider

M0 used the configured incumbent route `groq/openai/gpt-oss-120b` through LiteLLM alias `agent-fast` at the configured Groq OpenAI-compatible endpoint. The sanitized smoke artifact records a first short-token response that ended at the length limit, followed by one successful harmless completion. It records the returned model metadata and usage only; no response content or credentials were persisted. All 18 completed P0 traces recorded the configured model and `agent-fast` alias; the provider field was absent from those traces, so `Groq` is reported as the configured provider family. The provider key was absent from inspected gateway logs and M5D artifact scans.

M1 (`Qwen/Qwen3-30B-A3B-Instruct-2507`) was not executed under the preregistered local-resource block. No Qwen model was downloaded and no substitution was made. There is no model comparison or recommendation.

Stage 4 DEV regression was not run because no complete grounding candidate qualified for it. Release holdout was not executed; `selection.json` remains absent; production retrieval, prompt, model route, and Commerce tools are unchanged. M5D-C and Stage 6 have not begun.

## Historical/noncanonical evidence

The earlier gate and P0/P1 observations came from a dirty evaluation worktree; prior P2 observations span mixed implementation states. They are retained in the pre-canonical revision `7f82c565e7f9fc085f2d81c2c04a9861444837a1` and legacy local artifacts for audit only. They are explicitly excluded from this report, the canonical DEV selection, and every metric above. The historical observations have not been rerun or combined with the canonical run.

Machine-readable canonical summary: [m5d-b-dev-summary.json](../../evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json).
