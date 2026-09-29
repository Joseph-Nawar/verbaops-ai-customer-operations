# Stage 5 M5D — rag-v0.1 failure postmortem

**Scope:** Deterministic diagnostic review of the frozen M5C rag-v0.1 results. This report does not change the benchmark, labels, scores, selection, threshold, or production profile. The 24-case rag-v0.1 release holdout is **SPENT**; every holdout observation below is diagnostic only and is not evidence of performance on an untouched holdout.

**Reference results:** The committed M5C baseline records DEV hybrid Recall@5 96.43%, spent-holdout hybrid Recall@5 85.71%, answerable evidence-gate acceptance 20/84, and no-answer evidence-gate rejection 12/12. Grounded results remain citation precision 10/14 (71.43%), labeled groundedness 6/41 (14.63%), unsupported recognized factual units 35/41 (85.37%), expected-fact coverage 41/105 (39.05%), and retrieval evidence-gate accuracy 35/120 (29.17%). No scores were recalculated or replaced in the baseline.

## Evidence and counting method

The committed baseline is the authoritative source for aggregate scores. Local sanitized M5C files were available at:

- `artifacts/rag_eval_runs/m5c-grounded-46536024-d9c4-479e-a42d-7e1c783faedb/grounded_cases.jsonl` (120 final answers, citation locators, selected-evidence locators, and gate scores)
- `artifacts/rag_eval_runs/20260928TDEV-real-4/dev-retrieval.jsonl` (96 cases per strategy)
- `artifacts/rag_eval_runs/20260928T-HOLDOUT-real/release_holdout-retrieval.jsonl` (24 cases per strategy; spent holdout)

The retrieval files retain `ranked_locators` and candidate detail only through top five for each strategy. The grounded file retains selected-evidence locators, not the assembled text passed to the model. Neither retains the complete dense/lexical top-20 and pre-fusion candidate lists. The raw files are local and are not required by permanent CI.

Case-level counts below were computed by joining those records to the frozen v0.1 judgments and deterministic grounded-fact rules. C additionally requires exact equality between the grounded run's gate score and the saved hybrid RRF retrieval score; all 120 joined scores matched. Citation mismatch counts compare each emitted citation locator with that case's positive relevance judgments. Where the saved records do not expose the required stage data, the classification is marked unavailable.

## Failure-class results

“DEV / spent holdout” counts refer to cases unless the row explicitly says citation handles or factual units. Category counts list nonzero categories only.

| Class and pipeline stage | Count | DEV / spent holdout | Category counts | Representative cases | Evidence and limit |
|---|---:|---:|---|---|---|
| **A. DENSE_MISS** — dense retrieval top-20 | **Unavailable** | Unavailable | Unavailable | — | Saved retrieval records contain only dense top-five results. A miss at rank 1–5 does not prove a miss at rank 1–20. The baseline's Recall@5 results remain unchanged. |
| **B. FUSION_LOSS** — candidate fusion/ranking into final top-5 | **Unavailable; 0 confirmed in retained top-five traces** | Unavailable | Unavailable | — | Among retained dense/lexical top-five lists, no case showed a positive locator in a component top-five and absent from hybrid top-five. The component top-20 and full fused candidates were not saved, so the complete class cannot be counted. |
| **C. EVIDENCE_GATE_FALSE_REJECT** — frozen RRF evidence gate | **79 cases** | **61 / 18** | FAQ 12 (9/3); payments 8 (6/2); privacy 2 (0/2); product-guides 15 (11/4); refunds 9 (8/1); returns 11 (8/3); shipping 11 (9/2); warranty 11 (10/1) | DEV: `shipping-001`, `returns-001`, `warranty-001`; spent holdout: `shipping-014`, `privacy-007` | Gate score was below the frozen threshold, selected evidence was empty, and a positive judgment was present in the saved hybrid final top-five. This establishes false rejection before generation for these cases. The grounded file shows 20 accepted and 85 rejected answerable turns overall; the committed DEV calibration remains 20/84. |
| **D. CONTEXT_INSUFFICIENT** — evidence-context assembly | **Unavailable; 0 confirmed by labeled aliases in reconstructed selected chunks** | Unavailable | Unavailable | — | The run persisted selected locators, not supplied chunk text. Reconstructing canonical corpus chunks showed the labeled aliases in every positive selected chunk inspected, but that cannot prove the exact assembled prompt payload. No case is counted as confirmed. |
| **E. CITATION_OMISSION** — answer generation/finalization | **11 cases** | **11 / 0** | FAQ 2; payments 1; privacy 3; product-guides 2; refunds 1; returns 1; shipping 1 | `shipping-007`, `returns-006`, `privacy-004` | Selected evidence included a positive judgment, at least one labeled fact was recognized in the final answer, and no valid public citation handle was recorded. Some answers used non-resolving marker forms such as `【K1】`; these did not become application citation locators. |
| **F. CITATION_MISMATCH** — citation locator mapping | **3 cases / 4 citation handles** | **3 / 0** | FAQ 1 case / 1 handle; product-guides 1 / 1; refunds 1 / 2 | `refunds-001`, `product-guides-006`, `faq-011` | Four emitted locators did not match positive evidence: `faq-returns|2026.1|When is the refund sent?|2`, `refund-policy|2026.1|Timing|1`, `accessories|2026.1|Compatibility checks|2`, and `shipping-policy|2026.1|Tracking and delays|2`. The cases may also contain a correct citation; baseline citation precision remains 10/14. |
| **G. GENERATION_UNSUPPORTED** — labeled factual units with relevant pre-gate candidates | **35 cases / 35 recognized factual units** | **30 / 5** | FAQ 5 (5/0); payments 5 (4/1); privacy 3 (3/0); product-guides 13 (11/2); refunds 1 (1/0); returns 4 (3/1); shipping 3 (3/0); warranty 1 (1/0) | DEV: `product-guides-001`, `payments-002`; spent holdout: `payments-009`, `product-guides-018` | In all 35 cases, a positive judgment appeared in the saved hybrid final top-five and the deterministic evaluator recognized a labeled unit unsupported by emitted citations. This matches the baseline's 35/41 unsupported units. Twenty-four cases also overlap C: the gate rejected them before evidence was supplied. The count reports evaluator-recognized units; it does not independently establish that every match was an asserted hallucination. |
| **H. EVALUATOR_OR_LABEL_REVIEW** — human review flag, separate from system failures | **11 flags** | **10 / 1** | FAQ 2 (2/0); payments 2 (2/0); privacy 1 (1/0); returns 4 (3/1); shipping 1 (1/0); warranty 1 (1/0) | `returns-005`, `privacy-003`, `shipping-010`; spent holdout: `returns-015` | Nine responses mention a labeled topic while explicitly refusing to verify it; two plausible paraphrases were not recognized. These flags require review of alias matching/negation and are not score corrections. |

The classes can overlap. C is measured over gate-rejected answerable cases. E requires positive evidence to have been selected; G uses positive evidence in the saved hybrid final top-five before the gate, so 24 G cases also overlap C. F counts both cases and individual non-positive citation handles. H is a review queue, not a system-failure count.

### Evaluator/label review flags

- `returns-005`: The final answer states that eligible returns receive instructions and, where applicable, a prepaid return-shipping label. The deterministic expected-fact alias did not recognize this phrasing, although it appears consistent with the committed Returns Policy and FAQ.
- `privacy-003`: The final answer says customers can request to view or correct their personal data through support. The expected fact uses “request access to or correction of personal information”; the evaluator did not recognize the paraphrase.
- `shipping-010`, `returns-007`, `returns-010`, `returns-015`, `warranty-008`, `payments-006`, `payments-007`, `faq-006`, and `faq-010`: Each final answer explicitly says it cannot verify the policy, but repeats one of the expected-fact aliases in the refusal. The deterministic alias matcher counts those mentions as recognized unsupported units even though the response does not assert the fact. `returns-015` is a spent-holdout review flag.

All 11 remain review flags only. No LLM judge was used, no rag-v0.1 label or alias was edited, and no historical metric was rescored.

## RRF evidence-gate scale

The frozen profile uses reciprocal-rank fusion with `k = 60`, where one list contributes `1 / (k + rank)`:

- One rank-1 contribution: `1 / 61 = 0.01639344262295082`.
- Dense rank 1 plus lexical rank 1: `2 / 61 = 0.03278688524590164`.
- Frozen evidence-gate threshold: `0.032018442622950824`.

The threshold lies above one rank-1 contribution and just below two rank-1 contributions. That makes the raw score sensitive to where a chunk appears in the component lists and whether lists overlap. RRF is principally a ranking-fusion heuristic; its raw score is not automatically a calibrated measure of semantic relevance or answer sufficiency. This is an analysis of the frozen gate only. M5D-A does not change the production threshold or profile.

## Local M1 feasibility audit

On the current Windows machine, discovery reported 7.6 GiB system RAM, Intel UHD integrated graphics (reported adapter memory 2 GiB; no dedicated GPU/VRAM was identified), and no `nvidia-smi`. The `ollama`, `llama-server`, `llama-cli`, `vllm`, `lms`, and `lmstudio` commands were absent; Python imports for `vllm`, `llama_cpp`, and `torch` were also absent. No runtime or model was installed or started.

A 30B parameter model at four bits requires about 15 GB for raw weights before quantization metadata, runtime memory, and context cache. That already exceeds this machine's reported RAM. M1 is therefore recorded as **`M1_LOCAL_BLOCKED_RESOURCES`**. Qwen3-14B may be considered later as a separately preregistered lower-resource candidate; it is not substituted for M1 in this plan.

## M5D boundaries

This postmortem is diagnostic, not a retroactive tuning report. The v0.1 spent holdout was inspected only for failure analysis. The new rag-v0.2 release holdout remains sealed: no M5D selection artifact exists, and no v0.2 holdout case was executed. All production behavior remains frozen during M5D-A.
