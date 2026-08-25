# Stage 4 M4A Evidence Packet

Status: M4A only. Single-agent execution only. M4B has not begun.

## Source and commits

- Base SHA: `1f8f65ad7a9f86690c7b95cc7fc5b1d0791d6d21`
- Current head SHA: `e4e81ca`
- Branch: `stage4/m4a-evaluation-harness`
- Spec: `docs/superpowers/specs/2026-08-25-verbaops-stage4-evaluation-v1-design.md`
- Plan: `docs/superpowers/plans/2026-08-25-verbaops-stage4-m4a-evaluation-harness.md`
- Commits: `a8fd7ea`, `e646c92`, `3881c2a`, `042813e`, `8d1c20b`, `bfd1736`, `597faf7`, `36f65db`, `dd18416`, `97d34ec`, `35a583a`, `5d81d10`, `e4e81ca`

## Corpus

- Dataset: `text-agent-v0.1`
- SHA-256: `42fc86362e8e85bbe5ef4cf9d145ba0966f7616415981c28c5a2bd5449ef5367`
- Total: 120
- Split: 96 dev / 24 release_holdout
- Categories: order-status 20; shipment-status 20; refund-status 15; product-search 15; delivery-slots 10; missing-ambiguous-identifiers 15; unsupported-write 10; safety-injection-identity-cross-customer 10; benign-no-tool 5
- Audit proof: `make eval-corpus-check` exits 0 and prints the exact totals, category counts, and SHA above.

## Verification

- Deterministic metric tests: 7 passed.
- Evaluation/CI tests: 50 passed, 4 PostgreSQL tests skipped locally because no database URL was configured.
- Normal suite: `make check` passed; 503 passed, 4 skipped, 79 deselected; coverage 82.83%; pre-commit passed.
- Deterministic runner: `make eval-agent` passed all 120 fixture cases and wrote summary/results/failed-case artifacts with zero failures.
- Stage 3 focused agent/tool/LLM tests: 94 passed, 2 skipped.
- OpenAPI contract: `make commerce-contract-check` passed.
- Migration head: `0003_evaluation_v1`.
- Local Docker-dependent PostgreSQL/acceptance/web/runtime-build gates: Docker daemon unavailable locally; hosted CI is required for those gates.
- Hosted CI: run `32838869054` completed successfully; all 12 jobs passed. The independent `evaluation-contract` job reported 36 deterministic evaluation tests passed, 4 PostgreSQL persistence tests passed, and the 120-case deterministic adapter passed 120/120 with zero failures, zero unauthorized actions, and zero S4 violations.
- Draft PR URL: https://github.com/Joseph-Nawar/verbaops-ai-customer-operations/pull/13 (draft; not merged).

## Invariants and scope

- The five exact READ_ONLY tools are unchanged.
- Stage 3 prompt, graph topology, model routing, budgets, LangGraph pin, LiteLLM pin, Stage 2 OpenAPI hash, canonical seed fingerprint, Commerce source, and Commerce migration head are unchanged.
- No baseline artifact exists and no genuine model baseline is claimed.
- No prompt/model/tool optimization was performed.
- No RAG, writes, Arabic specialization, voice, HITL, multi-agent architecture, Langfuse, or LLM judge work was started.
