# Stage 5 RAG v0.1 baseline

Status: genuine retrieval benchmark and grounded-agent evaluation complete. The grounded run completed all 120 cases through the public Stage 5 agent path using the Stage 4 `agent-fast` model route.

Dataset: `rag-v0.1`, 120 cases: 96 DEV and 24 release holdout. Dataset SHA-256 is `05ee4c5064db8eafa7a1660f38fb3cb518965229fac8346593a93da75c1991f3`; the NovaCommerce manifest SHA-256 is `26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660`. The committed chunking parameters are 180 maximum tokens and 30 overlap tokens.

The fresh real-E5 ingestion produced 15 documents, 17 versions, and 55 chunks: 15 active versions, 2 superseded historical versions, 51 active chunks, and 4 superseded chunks. Stored vectors are 768-dimensional under `multilingual-e5-base-v1` / `intfloat/multilingual-e5-base`.

## DEV selection

The pre-registered rule selected `hybrid_rrf`. It tied dense at Recall@5 (`96.43%`) but had better MRR (`0.8391` vs `0.8093`) and nDCG@5 (`0.8683` vs `0.8460`), while remaining faster at p95 (`99.09 ms` vs `136.97 ms`). The reranked hybrid was slower (`666.10 ms` p95) and did not meet the DEV Recall@5 tie band (`95.24%`).

| Strategy | Recall@1 | Recall@5 | MRR | nDCG@5 | Retrieval p50 | Retrieval p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 69.64% | 96.43% | 0.8093 | 0.8460 | 89.31 ms | 136.97 ms |
| lexical | 22.02% | 22.02% | 0.2262 | 0.2176 | 2.58 ms | 3.74 ms |
| hybrid_rrf | 74.40% | 96.43% | 0.8391 | 0.8683 | 64.90 ms | 99.09 ms |
| hybrid_rrf_rerank | 73.21% | 95.24% | 0.8361 | 0.8635 | 374.75 ms | 666.10 ms |

Hybrid beat dense on Recall@1, MRR, nDCG@5, and p95 latency; Recall@5 was tied. Reranking did not improve the DEV hybrid result and was not worthwhile for the production default under the pre-registered rule.

Calibration selected threshold `0.032018442622950824` for the selected hybrid RRF top score. Acceptance is `score >= threshold`; abstention is `score < threshold`. DEV accepted 20/84 answerable cases and abstained on 12/12 no-answer cases, satisfying the mandatory 90% guard.

## Untouched holdout

The holdout was not opened until selection commit `af0e913d4f11df1d3faa155d4bbde801dd3603f2` was pushed. It was run once for all four strategies without changing labels, models, parameters, strategy, or threshold.

| Strategy | Recall@1 | Recall@5 | MRR | nDCG@5 | Retrieval p50 | Retrieval p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 47.62% | 85.71% | 0.6667 | 0.7151 | 97.71 ms | 165.11 ms |
| lexical | 0.00% | 0.00% | 0.0000 | 0.0000 | 2.59 ms | 4.80 ms |
| hybrid_rrf | 47.62% | 85.71% | 0.6667 | 0.7151 | 69.46 ms | 117.41 ms |
| hybrid_rrf_rerank | 61.90% | 88.10% | 0.7857 | 0.7936 | 396.25 ms | 670.78 ms |

The frozen production candidate is `hybrid_rrf`; its holdout Recall@5 was `85.71%`, below the evaluation-plan target of `90%`. The reranked alternative reached `88.10%` but was not permitted to replace the DEV-selected production candidate.

## Production profile

The active profile is `knowledge-retrieval-v1.1`, using hybrid RRF, dense/lexical limits 20, RRF `k=60`, fused limit 20, final limit 5, and the calibrated threshold above. Because reranking did not win DEV selection, the active path does not require the reranker; the alternative remains evaluation-only.

## Grounded-agent evaluation

The checkpoint-safe run `m5c-grounded-46536024-d9c4-479e-a42d-7e1c783faedb` completed all 120 `rag-v0.1` cases through the real public Stage 5 API, frozen `hybrid_rrf` retrieval profile, real E5-backed knowledge corpus, server-resolved citations, and application-owned traces. The run used the existing Stage 4 `agent-fast` route: `groq/openai/gpt-oss-120b` at Groq's OpenAI-compatible endpoint. The trace recorded model `groq/openai/gpt-oss-120b` and the `agent-fast` alias; its provider field was null. No LLM judge was used.

| Metric | Result |
| --- | ---: |
| Citation precision | 10/14 (71.43%) |
| Groundedness of recognized labeled factual units | 6/41 (14.63%) |
| Unsupported-claim rate over recognized labeled factual units | 35/41 (85.37%) |
| Expected-fact coverage | 41/105 (39.05%) |
| Agent abstention accuracy at the frozen threshold | 35/120 (29.17%) |
| Answer latency p50 | 4,984.56 ms |
| Answer latency p95 | 11,853.92 ms |
| Total cost with cost metadata | $0.0367569 across 120 observations |
| Mean cost with cost metadata | $0.0003063075 across 120 observations |
| Cost metadata coverage | 120/120 (100%) |

Abstention accuracy is scored from acceptance at the frozen threshold `0.032018442622950824` against the answerable/no-answer labels. Labeled groundedness checks recognized labeled factual units and does not detect every possible novel hallucinated claim outside the benchmark vocabulary. Retrieval selection, threshold, and holdout results were not changed or tuned; selected hybrid RRF holdout Recall@5 remains 85.71%, below the 90% reference target. Stage 6 has not begun.
