# Stage 5 M5D-B DEV Results

**Status:** provider-rate-limited; the grounding sweep is incomplete. These DEV results do not select a grounding policy or authorize production promotion.

## Scope and provenance

- Benchmark: `rag-v0.2`, DEV only, 96 cases (72 answerable and 24 no-answer).
- Dataset SHA256: `398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595`.
- Knowledge manifest SHA256: `26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660`.
- Frozen experiment-plan SHA256: `b9835dd0e7bb974480769d328f19d903cb9466828a0ac810200cc10b36251ba8`.
- Pre-experiment commit: `347eccfd7aaa22332bdf36ee396715133b716b9c`.
- The calibrated gate retained the frozen `knowledge-retrieval-v1.1` / `hybrid_rrf` ranking and the same final five evidence candidates. It changed only the evidence-confidence signal for evaluation.
- Gate cases, scores, stable locators, timings, and per-case provenance are in [gate-cases.jsonl](../../evals/rag/v0.2/dev-evidence/gate-cases.jsonl). Sanitized aggregates and candidate reports are in [m5d-b-dev-summary.json](../../evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json).

## Evidence-gate calibration

Thresholds were calibrated independently per gate from observed DEV scores. Eligibility required at least 22/24 no-answer cases rejected. The selected signal maximized answerable acceptance among eligible candidates; candidate score scales were not compared across gates.

| Candidate | Threshold | Answerable accepted | No-answer rejected | Total p95 |
| --- | ---: | ---: | ---: | ---: |
| G0_CURRENT_RRF | 0.02964254577157803 | 13/72 (18.06%) | 24/24 (100%) | 160.64 ms |
| G1_DENSE_SIMILARITY | 0.8573166988459672 | 40/72 (55.56%) | 22/24 (91.67%) | 172.58 ms |
| G2_TOP_EVIDENCE_CROSS_ENCODER | 0.2554669 | 56/72 (77.78%) | 22/24 (91.67%) | 397.47 ms |

**DEV-selected gate:** `G2_TOP_EVIDENCE_CROSS_ENCODER` at `0.2554669`. The 70% answerable-acceptance target and 90% no-answer rejection guard both passed. This is a DEV-only selection; it was not promoted.

## Grounding candidates

Only P0 and P1 completed all 96 DEV cases. Metrics use deterministic rag-v0.2 labeled-fact recognition and server-resolved citations. Groundedness covers recognized labeled factual units; it does not measure every possible novel claim.

| Metric | P0_CURRENT | P1_PROMPT_V3 |
| --- | ---: | ---: |
| Citation precision | 12/19 (63.16%) | 52/82 (63.41%) |
| Labeled groundedness | 0/4 (0%) | 2/2 (100%) |
| Unsupported recognized-fact rate | 4/4 (100%) | 0/2 (0%) |
| Expected-fact coverage | 4/72 (5.56%) | 2/72 (2.78%) |
| Accepted-evidence citation compliance | 12/58 (20.69%) | 54/58 (93.10%) |
| Safe fallback | 0/96 (0%) | 0/96 (0%) |
| Answer latency p50 | 5,382.29 ms | 3,657.34 ms |
| Answer latency p95 | 12,884.26 ms | 13,824.63 ms |
| Cost total over costed observations | $0.0268023 (96/96) | $0.0237015 (96/96) |
| Mean cost over costed observations | $0.00027919 | $0.00024689 |
| Cost metadata coverage | 96/96 (100%) | 96/96 (100%) |

The cost totals and means cover only the 96 observations for the corresponding candidate. They are not combined across candidates.

Neither completed candidate meets the preregistered grounding floors. P0 misses citation precision, groundedness, unsupported-fact rate, and expected-fact coverage. P1 meets the groundedness and unsupported-fact floors on its small recognized-fact denominator, but misses citation precision and expected-fact coverage by wide margins.

P2 completed 39/96 cases before provider failures interrupted the run. Its partial checkpoint is not scored or used for eligibility. P3 was not started. No grounding policy was selected.

## Model and provider

M0 used the incumbent route `groq/openai/gpt-oss-120b`, capability alias `agent-fast`, through the configured Groq OpenAI-compatible endpoint. The sanitized smoke verified the gateway, alias resolution, and one successful request. Provider metadata from the gateway/trace was null or omitted; the configured provider family was recorded as `groq`. No response content or credentials were printed.

M1 (`Qwen/Qwen3-30B-A3B-Instruct-2507`) was not executed. Its three local endpoint environment variables were missing, and the M5D-A feasibility audit recorded local resource constraints. No Qwen model was downloaded. M0 was the only executable model; no comparative model recommendation was made.

## Provider block and experiment order

P2 stopped after an application HTTP 503 on an unsaved DEV case. The isolated application trace recorded `agent_unavailable` and the associated `agent-fast` model call recorded `llm_unavailable`. Gateway diagnostics showed provider HTTP 429 rate-limit responses. The provider key was absent from the inspected gateway logs. Checkpointed cases were preserved; retries of the same pending case after cooldown did not complete it. The run was stopped without changing the model or provider.

The preregistered order therefore stops before a grounding selection, Stage 4 DEV regression, and M1 comparison. No completed eligible grounding candidate exists to send to the Stage 4 regression check.

## Decision and frozen boundaries

- Decision status: `PROVIDER_RATE_LIMIT_BLOCKED_INCOMPLETE_GROUNDING_SWEEP`.
- DEV-selected gate: G2 at `0.2554669`; not promoted to production.
- Selected grounding candidate: none.
- Stage 4 DEV regression: not run because no completed eligible grounding candidate exists.
- M1 comparison: not run; no executable challenger endpoint.
- `evals/rag/v0.2/selection.json`: absent.
- Release holdout: not executed.
- Production retrieval profile, production prompt, agent-fast route, and five Commerce tools: unchanged.
- Production promotion: false. M5D-C and Stage 6 have not begun.

Machine-readable decision: [dev-decision.json](../../evals/rag/v0.2/dev-decision.json).
