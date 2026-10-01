# M5D-B2 Scorer-v2 and P4 Preregistration

**State:** provider-free preregistration only. P4 runtime behavior is not implemented, and no P4 result artifact exists.

## Scorer-v2 freeze

Scorer `rag-v0.2-scorer-v2` has a fact-specific positive paraphrase for every one of the 72 answerable DEV facts. It recognizes a benchmark-labeled expected fact only when a complete benchmark alias or independently authored, preregistered paraphrase is directly asserted. It returns diagnostic statuses for partial, negated, contradicted, refusal, quoted, uncertain, unrelated-overlap, and unrecognized text. Only `asserted` contributes to fact recognition. The helper does not judge arbitrary free-form claims.

Each of the 72 fixture records binds its benchmark statement, aliases, supporting locator, exact excerpt, source path, and one manually authored positive paraphrase to the committed DEV dataset and corpus. Paraphrases and the compact negative regression matrix were authored from those sources without consulting candidate responses; P2/P3 answer text was not used, and P4 outputs were unavailable. The manifest binds all fact IDs, dataset and knowledge-manifest hashes, source-document hashes, fixture/spec/implementation SHA256 values, freeze date, and definition commit. The negative matrix covers a compound conditional fact, a numeric time window, and inherently negative facts.

The scorer definition anchor is commit `fa800f5bfee4ee903905d89bf600642e9ddb0d95`. Its frozen implementation is `src/verbaops/evaluation/rag_v02_scorer_impl.py` with SHA256 `aa0eff0b165a8d40e22416bad493f432931409ca70d2abee89682966c39df67a`; the audit wrapper exposes no scorer entry point. The P4 model input excludes benchmark labels, expected facts, aliases, and answer keys.

Exact aliases plus one fact-specific paraphrase per answerable DEV fact form a deterministic contract. Unrecognized phrasing remains unrecognized; the scorer does not infer semantic equivalence from term overlap. Refusal, uncertainty, negation, contradiction, quoted mention, and partial assertion never count as full fact coverage. Negative wording that is itself part of a correctly matched fact, such as a policy exclusion, remains a positive assertion of that labeled fact.

## P4 candidate

The only candidate is `P4_EVIDENCE_LINKED_SINGLE_PASS`. One normal model generation returns a strict object containing a `claims` array. Each factual claim has `claim_text`, one `evidence_handle`, and one `supporting_excerpt`. There is no global citation list.

One normal structured final-answer generation returns the claims. Existing Commerce tool selection and authorization remain in the public path under the frozen budgets. The future application validates the object shape, verifies that each handle belongs to the selected evidence supplied to that request, requires each excerpt to be a non-empty exact substring of that source, and requires each claim text to be a non-empty literal exact substring of its excerpt. It renders only validated claim records. If none remain, it uses the existing deterministic safe fallback. No repair generation, second final-answer pass, reranker, category router, model switch, tool change, authorization change, or budget change is included.

**Extractive validation proves the rendered claim text occurs in the cited source excerpt and that the excerpt comes from supplied evidence; it does not establish every possible contextual interpretation of that source.** Benchmark relevance and scorer metrics remain the quality evaluation.

## P4 observability

Sanitized evaluation traces must retain the structured assistant response, parse result, every proposed claim/handle/excerpt, handle and excerpt validation results, deterministic rejection reason, rendered claims, and fallback reason. Credentials, request headers, and unrelated private data are excluded. These fields let the report distinguish generation omission, malformed output, invalid handles, excerpt mismatch, deterministic filtering, and scorer nonrecognition.

## Experiment contract

- Run one canonical evaluation of all 96 DEV cases through the public application path. Do not rerun P0/P2/P3 or access release holdout. Keep `selection.json` absent.
- Keep the application-under-test SHA separate from the evaluation-harness SHA. Bind the dataset, knowledge manifest, experiment plan, scorer version/manifest/fixture hashes, gate and threshold, candidate, model revision, prompt/graph/retrieval versions, run ID, and hosted freeze-CI evidence in run identity.
- Before any P4 provider request, require a committed freeze SHA and successful hosted CI on that exact SHA, with every required job green. The provider-free gate helper rejects missing, mismatched, failed, or incomplete CI evidence.
- Budget 96 public case requests and at most four model calls per case (384 total runtime ceiling). That is a ceiling, not a promised number of calls. P4 adds no repair call. Stop at the first explicit quota failure and retain the checkpoint; do not automatically retry. Do not score incomplete runs. Classify deterministic runtime failures as execution-ineligible without retrying the failed case.
- Keep quality floors unchanged: citation precision at least 0.95 with nonzero denominator; labeled groundedness at least 0.90 with nonzero denominator; unsupported recognized-fact rate at most 0.10; expected-fact coverage at least 0.70. Also require zero fabricated or non-supplied evidence handles.
- Run Stage 4 DEV only if P4 passes every RAG floor. M5D-C remains blocked until P4 completes 96/96, stays execution-eligible, passes the frozen scorer-v2 floors and required Stage 4 DEV regression, and has complete provenance. Freeze the candidate before any new release-holdout use.

The machine-readable plan is [m5d-b2-experiment-plan.json](../../evals/rag/v0.2/m5d-b2-experiment-plan.json); scorer provenance and fixtures are under [scorer-v2](../../evals/rag/v0.2/scorer-v2/).
