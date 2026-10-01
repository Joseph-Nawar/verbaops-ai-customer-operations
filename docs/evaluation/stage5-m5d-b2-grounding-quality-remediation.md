# M5D-B2 — DEV Grounding Quality Forensics and Proposal

**Status:** analysis and design proposal only. No candidate was implemented or executed. No provider calls were made.

This analysis uses the merged, hash-bound M5D-B canonical DEV artifacts. It does not change M5D-B reports, scores, candidate status, the frozen gate, or any production behavior.

## 1. M5D-B final baseline

The application-under-test is `7f82c565e7f9fc085f2d81c2c04a9861444837a1`; the evaluation-harness correction is `86c81196e7ed4c967eec62bfc2cab9484820529c`. The selected evidence gate remains `G2_TOP_EVIDENCE_CROSS_ENCODER` at `0.2554669`.

| Candidate | Cases | Citation precision | Labeled groundedness | Unsupported recognized fact rate | Expected-fact coverage | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| P0_CURRENT | 96/96 | 12/18 = 66.67% | 2/4 = 50.00% | 2/4 = 50.00% | 4/72 = 5.56% | Complete; quality-ineligible |
| P1_PROMPT_V3 | 16/96 | — | — | — | — | Execution-ineligible after frozen `agent_budget_exceeded`; unscored |
| P2_FAIL_CLOSED_CITATIONS | 96/96 | 48/71 = 67.61% | 0/0; undefined | Undefined | 0/72 = 0.00% | Complete; quality-ineligible |
| P3_ONE_REPAIR_THEN_FAIL_CLOSED | 96/96 | 50/79 = 63.29% | 1/1 = 100.00% | 0/1 = 0.00% | 1/72 = 1.39% | Complete; quality-ineligible |

P1's partial metrics are not treated as representative. The committed decision is `NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE`. The gate accepted 56/72 answerable cases and rejected 22/24 no-answer cases. Release holdout remains untouched, and `selection.json` is absent.

P2 had 9 safe fallbacks across DEV; P3 had 6. P3 attempted 9 repairs, with 3 recorded successes and 6 failures. Its one recognized grounded fact is a one-unit denominator and does not support a broad quality claim.

## 2. Case-level failure taxonomy

The reproducible per-case evidence is in [m5d-b2-case-taxonomy.jsonl](../../evals/rag/v0.2/analysis/m5d-b2-case-taxonomy.jsonl). It contains one record for every one of the 72 answerable DEV cases, with expected fact IDs/statements/aliases and locators, frozen G2 confidence/decision, final-five locators, each candidate's selected evidence, final answer, resolved public citations, model/tool counts, fallback and repair fields, and one primary class per candidate. The generator marks raw pre-finalization answers and raw citation handles unavailable rather than reconstructing them.

The G2/final-five decomposition is:

| Evidence path | Cases | Share of 72 |
| --- | ---: | ---: |
| Expected support absent from final five (`RETRIEVAL_MISS`) | 3 | 4.17% |
| Expected support in final five, but G2 rejected (`GATE_REJECTED_RELEVANT_EVIDENCE`) | 13 | 18.06% |
| G2 accepted with expected support in final five and selected evidence | 56 | 77.78% |

The three retrieval misses are `m5d-v02-shipping-004`, `m5d-v02-returns-002`, and `m5d-v02-warranty-008`. The 13 relevant-support gate rejections are `m5d-v02-shipping-001`, `shipping-009`, `returns-007`, `returns-010`, `payments-001`, `payments-002`, `payments-006`, `product-guides-001`, `product-guides-003`, `product-guides-004`, `product-guides-009`, `product-guides-011`, and `faq-007` (all with the `m5d-v02-` prefix).

Every one of the 56 answerable G2-accepted records in each complete candidate contains the expected supporting locator in selected evidence. The final answer and citation outcomes are:

| Candidate | Expected fact recognized by frozen evaluator | Expected-support locator appears in public citations | Accepted cases with exact safe fallback |
| --- | ---: | ---: | ---: |
| P0 | 4/72 | 12/72; 2 of 4 recognized facts also cite support | 0/56 |
| P2 | 0/72 | 48/72, including 48/56 accepted cases | 8/56 |
| P3 | 1/72 | 50/72, including 50/56 accepted cases | 6/56 |

Among those 56 accepted cases, expected-support citations were absent in 44/56 P0, 8/56 P2, and 6/56 P3 records (78.57%, 14.29%, and 10.71%, respectively). Those are case-level citation-presence failures; exact claim-span citation attachment is not stored. The frozen evaluator did not recognize 52/56 P0, 56/56 P2, and 55/56 P3 accepted answers. Those are evaluator nonrecognition rates, not valid generation-omission rates, because the audit below found multiple clear paraphrases. The only directly countable empty-answer outcome on accepted cases is exact safe fallback: 0/56, 8/56, and 6/56. None of the 56 accepted answerable cases invoked a tool in P0, P2, or P3 (0/56 each). The machine-readable taxonomy marks 8 P0, 31 P2, and 27 P3 accepted answers as evaluator-review flags where the labeled-fact matcher missed an answer with high fact-term overlap and a citation to case-relevant evidence. These are flags, not corrected scores.

### Primary classes and uncertainty

The taxonomy assigns `RETRIEVAL_MISS` to the 3 absent-support cases and `GATE_REJECTED_RELEVANT_EVIDENCE` to the 13 support-present rejects. On accepted turns it distinguishes `EVALUATOR_RECOGNITION_GAP` review flags, exact fallback responses, and `OTHER` where final-answer omission cannot be attributed from saved evidence. A recognized fact with no citation is `CITATION_MISSING`; a recognized fact whose public citations do not include its support locator is `CITATION_WRONG_SUPPORT`.

The committed records do not contain raw pre-finalization model messages, tool names/arguments/results, unresolved citation handles, or claim-to-citation spans. Therefore the evidence cannot reliably separate model omission from finalizer removal, identify which Commerce tool ran in P0/P2/P3, or prove which sentence a message-level citation supports. The final answers and trace counts are present. The taxonomy leaves those unobserved stages explicit instead of guessing.

## 3. Root-cause decomposition

### Retrieval and evidence gate

Retrieval missed expected support in only 3/72 answerable cases. G2 rejected 13 more cases even though their support was in the final five. Those 16 cases are real upstream losses, but G2 still accepted 56/72 answerable cases and 22/24 no-answer cases were rejected. In every accepted answerable turn the expected support reached selected evidence. Most of the remaining coverage gap therefore occurs after evidence selection, not because the accepted evidence lacked the labeled locator.

Keep the gate frozen for the next experiment. The 13 false rejects merit future study, but retuning G2 does not address the observed behavior on its 56 accepted, support-bearing cases.

### Generation, finalization, and evaluator recognition

The frozen recognition helper in `rag_v02.py` matches a supplied alias as a normalized phrase in one answer clause and excludes several explicit refusal/negation patterns. It does not recognize free paraphrase. Examples from the committed outputs include:

| Case | Labeled fact | Final answer pattern | Forensic reading |
| --- | --- | --- | --- |
| `m5d-v02-shipping-002` | Express delivery normally arrives in one to two business days after dispatch. | “Express parcels are delivered within one to two business days after dispatch.” | Direct paraphrase; exact alias matcher missed it. |
| `m5d-v02-shipping-008` | Carrier scans can take one business day to appear. | “Carrier hand-off scans… can take up to one business day… before it appears.” | Direct paraphrase; exact alias matcher missed it. |
| `m5d-v02-warranty-003` | Warranty service covers repair, replacement, or another remedy selected under the terms. | The response lists repair, replacement, or another company-selected remedy under the terms. | Near-verbatim semantic match; exact alias matcher missed it. |
| `m5d-v02-product-guides-012` | A higher-wattage charger is not automatically faster or safer. | “A charger’s wattage alone does not guarantee faster or safer charging.” | Direct paraphrase; exact alias matcher missed it. |

The source-level examples are not a rescoring of P2/P3. Across all 96 records, P2 cited a locator with positive case relevance 48 times out of 71 citations, while the labeled-fact recognizer returned zero facts. P3 cited positive case-relevant locators 50 times out of 79, while the recognizer returned one fact. For the 72 answerable cases, the expected supporting locator appears in 48 P2 and 50 P3 public-citation records. This large disagreement, plus the review flags in the case file, shows that the reported 0/72 and 1/72 coverage cannot be read as “the model stated no expected facts.”

There are also genuine safe-fallback omissions: 8 P2 and 6 P3 accepted answerable cases ended in the exact deterministic fallback. Other accepted, non-recognized answers remain a mixture of possible paraphrase, partial fact, and actual omission. Because raw model output before finalization is unavailable, the current evidence cannot quantify the generation-versus-finalizer split. Novel unsupported claims are outside the evaluator's labeled-fact scope.

### Citation precision

| Candidate | Positive under case relevance judgments | Non-positive/unjudged | Citations outside supplied evidence |
| --- | ---: | ---: | ---: |
| P0 | 12/18 | 6/18 | 0 |
| P2 | 48/71 | 23/71 | 0 |
| P3 | 50/79 | 29/79 | 0 |

Every saved public citation locator is among that case's supplied selected evidence. The precision failures are therefore not evidenced as stale or fabricated locator handles; they are citations to supplied passages that are not positive under that case's relevance judgments. P2 has one citation on a no-answer case; P3 has three. The records do not retain unresolved citation handles, so unresolved-handle failure frequency is unknown. Since citations are stored at message level, claim/citation entailment cannot be computed from these artifacts.

The strongest observed citation mechanism is that the model/finalizer can emit several citations from the noisy final-five context, including non-positive passages. Fail-closed citations ensured citations were present more often, but did not guarantee that each cited passage was positively relevant to the question or supported the answer. P3's repair increased citation volume by 8 versus P2, with only 2 more positive citations; full-run precision fell from 67.61% to 63.29%.

### Expected-fact coverage decomposition

For each candidate, the 72 expected-fact opportunities divide as follows:

| Path | P0 | P2 | P3 |
| --- | ---: | ---: | ---: |
| Support missing from final five | 3 | 3 | 3 |
| Support retrieved but rejected by G2 | 13 | 13 | 13 |
| G2 accepted; exact labeled fact recognized | 4 | 0 | 1 |
| G2 accepted; exact safe fallback | 0 | 8 | 6 |
| G2 accepted; final answer not recognized and not exact fallback | 52 | 48 | 49 |

For P2/P3, the last row includes the high-overlap evaluator-review cases and unresolved lower-overlap cases. The 48 P2 and 50 P3 support-locator citations occur on accepted answerable cases; one P3 fact is also recognized by the frozen matcher. These are strong evaluator-brittleness signals, but not a new gold score. Actual semantic fact completion should be re-evaluated under a separate preregistered evaluator contract before any new candidate is measured.

Category-level outcomes, the exact IDs for every evaluator-review flag, all 72 full answers, and locators are in the taxonomy and [aggregate JSON](../../evals/rag/v0.2/analysis/m5d-b2-forensic-aggregates.json). Source hashes and canonical application/harness provenance are in [delta and citation audit JSON](../../evals/rag/v0.2/analysis/m5d-b2-delta-and-citation-audit.json).

## 4. P2 versus P3

P2 and P3 are separate M0 application executions, not paired replay of identical model responses. Their answer text differs in 69/72 answerable cases; citation lists differ in 15/72; presence of a citation to the expected support locator differs in 8/72. Only three answer texts are identical: `m5d-v02-shipping-005`, `m5d-v02-returns-001`, and `m5d-v02-refunds-001`. The outputs cannot isolate a repair-only causal effect; model response variation and the added repair path are not separable in the saved records.

P3 recorded 9 repair attempts, 3 successes, and 6 failures. Eight attempts were on answerable cases: 2 successes and 6 failures. The two answerable successes were `m5d-v02-warranty-005` (P2 fallback versus P3 non-fallback with citations) and `m5d-v02-warranty-006` (both candidates had the same two public citation locators, with different answer text). The third recorded success was on `m5d-v02-no-answer-012`; P3 returned two citations there, neither positive under the no-answer relevance labels.

The six failed repairs ended in the deterministic fallback at `shipping-005`, `returns-001`, `refunds-001`, `refunds-003`, `warranty-004`, and `product-guides-010`. In the separate P2 observations, P2 had non-fallback cited answers for `refunds-003`, `warranty-004`, and `product-guides-010`; that is a descriptive cross-run contrast, not proof that P3 discarded those exact P3 pre-repair answers. The P3 raw pre-repair responses were not committed.

P3 improved accepted-evidence citation compliance (52/58 versus P2's 49/58), reduced fallback count, and cited the expected support locator on two more answerable cases. It did not improve the frozen expected-fact coverage meaningfully (0/72 to 1/72), and its overall citation precision was lower. The adapter's “repair success” means a citation row existed and the final answer was not the safe fallback; it does not assert semantic correctness or citation precision.

## 5. Evaluator audit

The `rag-v0.2` recognizer is intentionally narrow: normalize punctuation/case, look for a whole supplied alias inside a clause, and suppress known refusal/negation patterns. It is deterministic, but its positive path is alias containment rather than semantic equivalence. P2/P3 output examples above assert labeled facts with different surface wording and cite the labeled support locator, yet remain unrecognized. The review screen flagged 31 P2 and 27 P3 cases using high content-term overlap plus accepted evidence and a positive case citation. The JSONL records include each flag and answer so every flagged case can be inspected; the flag is not used to change any M5D-B metric.

The audit also found genuinely empty safe-fallback responses and likely partial answers among cases with compound expected facts. Thus evaluator brittleness is material, but it does not explain all failures. No independent claim-span citation evidence or pre-finalizer output is available. A future evaluator must distinguish full assertion, partial assertion, refusal mention, and negation with explicit deterministic regression tests. No LLM judge should be used, and the updated evaluator must be frozen before new candidate inference.

## 6. Tool-routing audit

The committed grounded records store tool-call counts but not invocation names. Among the 72 answerable cases:

| Candidate | Cases with any tool call | Tool-call count | Policy-category cases with calls |
| --- | ---: | ---: | --- |
| P0 | 1 | 1 | 0 |
| P2 | 6 | 8 | `shipping-004`, `returns-010`, `payments-006` |
| P3 | 3 | 7 | `shipping-001`, `warranty-008` |

P0's tool case was `product-guides-003`; P2 also called tools on `product-guides-001`, `product-guides-009`, and `product-guides-011`; P3 also called tools on `product-guides-011`. All of these tool-using answerable cases were G2 rejects, and none was among the 56 accepted cases. The policy questions appear unnecessary for Commerce lookup from their query/category, but exact tool names and results are unavailable for P0/P2/P3, so “unnecessary” is an intent-based review, not a trace-proven tool attribution. The earlier P1 failure diagnosis separately proves three `search_products` calls on the policy-only `returns-007` case.

Observed tool calls were higher in the P2/P3 runs than P0 (1 versus 8/7 answerable calls), and policy-category case counts were 0 versus 3/2. This does not establish that prompt v3 caused the increase: the executions are separate model samples and P2/P3 contain additional candidate behavior. Tool routing did not account for missing expected facts in accepted cases because no accepted answerable turn invoked a tool. It may waste budget and latency on gate-rejected policy questions, as P1 demonstrated, but it is not the dominant source of the 56 accepted-case coverage result.

## 7. Recommended minimal candidate — proposal only

Before another agent candidate is measured, preregister and freeze a corrected deterministic fact-recognition contract. Build case-specific positive and negative assertion tests from the expected facts and committed corpus, with the answer text hidden from the reviewers who prepare those tests. The contract must recognize supported paraphrase, partial compound facts, refusal/negation mentions, and contradictions. Keep all original M5D-B metrics immutable; if old answers are audited under the new contract, publish them as a separate shadow analysis and do not overwrite the committed reports.

The smallest credible behavior candidate is **P4_EVIDENCE_LINKED_SINGLE_PASS**:

- Keep the selected G2 gate, `0.2554669` threshold, hybrid retrieval ranking, final five, M0 model/provider, public application path, tools, graph budgets, and authorization rules unchanged.
- In one normal generation, require structured answer claims with a server-issued evidence handle and an exact supporting excerpt for each factual claim.
- The application accepts only handles in the supplied final-five evidence and validates each excerpt as an exact substring of that source. Render only validated claim/evidence pairs; if no pair validates, use the existing deterministic safe fallback.
- Do not add a repair call, reranker, learned classifier, query-category tool router, or model switch.

This targets the observed problem that citations can point to supplied but non-positive distractor chunks and are not tied to a specific factual claim. It may improve citation precision by making each rendered claim auditable against one selected source. Expected-fact coverage should be measured with the preregistered scorer v2; the current coverage metric is too brittle to predict a behavioral effect. Security improves by keeping locators server-issued and refusing arbitrary model-created links. The extra JSON/quote tokens and validation add modest per-response work, but no intended additional model/tool call; malformed output can increase fallback. The quote check proves source provenance, not semantic entailment, so the scorer and review report must retain that limitation.

This is simpler than another repair loop or additional relevance model: one structured response plus deterministic checks reuses the existing evidence and gateway path. It is one related behavior change, not a bundle of retrieval and routing experiments.

## 8. Alternatives rejected

- **Prompt-only strengthening:** P2/P3 already use v3-style grounding instructions and often cite the expected support locator. More wording alone does not address wrong extra citations or evaluator paraphrase misses.
- **Another repair attempt:** P3 already tried one repair; 6/9 attempts failed, 3/9 succeeded by the narrow adapter definition, and overall precision fell despite two extra positive citations.
- **G2 retuning:** G2's 56/72 answerable acceptance and 22/24 no-answer rejection are useful. Only 3 supports are absent from final five and 13 support-bearing cases were rejected; the dominant observed group is the 56 accepted cases.
- **Category-based tool suppression:** no accepted answerable turn used tools. This would not fix the observed accepted evidence/citation/evaluator mismatch and could harm real Commerce intents.
- **Model/provider replacement or a combined classifier:** the current results do not isolate a model-quality problem, and added inference components increase cost without addressing the measured citation/evaluator mechanisms.
- **Expanding aliases from observed P2/P3 answers:** that would bake evaluated outputs into the scorer. A new contract must be built from frozen facts/corpus and independently reviewed before candidate responses are opened.

## 9. M5D-B2 experiment proposal

1. Preregister the scorer-v2 definition, deterministic tests, P4 output schema/finalizer, source identity, and stop rules before provider inference. Preserve the existing evidence and old M5D-B scores unchanged. Any offline rescoring of P0/P2/P3 must be labeled shadow analysis, not replacement results.
2. Run P4 on all 96 DEV cases once, through the public application and canonical run-identity/checkpoint mechanism. Keep G2 and all production behavior outside the candidate unchanged. Do not use release holdout, make smoke/diagnostic calls, replay baseline runs, or retry a completed/failed case.
3. Budget exactly 96 public application case requests, with a hard ceiling of 4 model calls per case under the frozen runtime: at most 384 M0 provider calls total. Historical 96-case P2/P3 executions used 105/113 model calls, respectively; use that only as a planning estimate, not a guarantee. No candidate-specific repair calls are planned. Stop at the first provider quota block or deterministic runtime failure and preserve the checkpoint.
4. Require canonical completion 96/96, complete identity/artifact hashes, and execution eligibility. Use the existing floors without weakening them: citation precision >=95% with nonzero denominator, labeled groundedness >=90% with nonzero denominator, unsupported recognized fact rate <=10%, and expected-fact coverage >=70%. Add zero fabricated/non-supplied citation handles as a trust invariant, not a replacement quality floor.
5. Run Stage 4 DEV regression only if P4 passes every RAG floor; require zero S4 violations, zero unauthorized actions, and all preregistered regression/tolerance guards. If any RAG floor fails, stop after P4 and record no qualifying candidate. Do not adapt the prompt/schema or retry based on the result.
6. Keep release holdout sealed and do not create `selection.json` during M5D-B2. Freeze the candidate and complete provenance before any future release-holdout use.

## M5D-C entry criteria

M5D-C cannot start until a new preregistered DEV candidate completes all 96 cases canonically, remains execution-eligible, passes every frozen grounding floor under a scorer frozen before inference, passes required Stage 4 DEV regression, and has complete application/harness/run/artifact provenance. Only after candidate and thresholds are frozen may a new release holdout be authorized. No release holdout was run in this analysis.

## Reproduction and provenance

Run `uv run python scripts/analyze_m5d_b2_forensics.py` to regenerate the three machine-readable analysis files. It reads only committed local DEV artifacts and the frozen dataset; it makes no provider calls. The delta/citation audit JSON binds SHA256 values for each input artifact and both analysis-tool files, identifies application SHA `7f82c565e7f9fc085f2d81c2c04a9861444837a1` and harness SHA `86c81196e7ed4c967eec62bfc2cab9484820529c`, and records `release_holdout_executed=false`, `selection_json_present=false`, and `provider_calls_made=false`.
