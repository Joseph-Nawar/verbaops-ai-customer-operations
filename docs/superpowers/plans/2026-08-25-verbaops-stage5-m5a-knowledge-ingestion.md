# Stage 5 M5A Knowledge Ingestion Implementation Plan

> SINGLE-AGENT execution only. Use direct task-by-task execution in this session. DO NOT use subagents. Do not use `superpowers:subagent-driven-development`.

**Goal:** Build the approved Stage 5 M5A versioned knowledge corpus and provider-free asynchronous ingestion system without implementing M5B retrieval behavior.

**Architecture:** Add a tenant-scoped knowledge domain with pure validation, normalization, Markdown section detection, deterministic chunking, hashes, and an application-owned 768-dimensional embedding client. Persist documents, versions, chunks, and ingestion jobs in PostgreSQL; use Redis/Celery only for delivery; expose tenant-admin upload/status/activation routes through the existing trusted-context and error-envelope patterns.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy async, Alembic, PostgreSQL 16 + pgvector, Redis, Celery, httpx, pytest, Ruff, mypy, pre-commit, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-25-verbaops-stage5-production-rag-v1-design.md`

## Global Constraints

- SINGLE-AGENT execution only; never use subagents.
- Base is `46a69bf3e18f4aaba3505887bd039ca3a7288ffe` and the branch is `stage5/m5a-knowledge-ingestion`.
- Add exactly one VerbaOps migration: `0004_knowledge_rag_v1`; Commerce migration head remains `0001_create_commerce_schema`.
- M5A must not implement M5B dense/lexical retrieval, RRF, reranking, citations, abstention, Arabic corpus, write tools, Stage 6, voice, or Langfuse.
- RAG owns policies, FAQs, product guides, and support/company knowledge only; live commerce truth remains in the five established Commerce read tools.
- Never log uploaded source wholesale; tenant identity comes only from `TrustedContext.tenant_id`.
- Embeddings use capability alias `embedding-multilingual`, OpenAI-compatible `/v1/embeddings`, and dimension 768; CI is provider-free.

## File map and interfaces

- Create `knowledge/novacommerce/manifest.json` and the required English policy, guide, FAQ, and historical Markdown corpus; `scripts/ingest_knowledge_corpus.py` validates and ingests it.
- Create `migrations/versions/0004_knowledge_rag_v1.py`; add `src/verbaops/knowledge/repository_tables.py` for SQLAlchemy table definitions and `src/verbaops/knowledge/models.py` for domain records/status enums.
- Create `src/verbaops/knowledge/validation.py`, `parsing.py`, `chunking.py`, and `embeddings.py`. Pure interfaces are `validate_upload(...) -> ValidatedUpload`, `normalize_markdown(...) -> str`, `detect_sections(...) -> list[Section]`, `chunk_sections(...) -> list[ChunkDraft]`, and `EmbeddingClient.embed(texts: Sequence[str]) -> list[list[float]]`.
- Create `src/verbaops/knowledge/repository.py` and `service.py`. Repository methods are tenant-scoped `create_or_get_document`, `create_version_and_job`, `get_job`, `ingest_version`, and `activate_version`; the service owns validation, security, lifecycle, transaction boundaries, idempotency, and sanitized domain errors.
- Create `src/verbaops/worker/celery_app.py` and `src/verbaops/knowledge/tasks.py`; the Celery task accepts `ingestion_job_id: UUID`, opens ordinary service dependencies, and returns the job outcome without owning business logic.
- Create `src/verbaops/api/routes/knowledge_admin.py`; add dependencies/resources only through established `ApplicationDependencies`, `RuntimeResources`, `get_database_session`, `get_redis_client`, and `get_trusted_context` patterns.
- Modify only necessary dependency lock/config, lifespan/app/router, Compose/CI, and test marker/config files. Do not alter Stage 4 agent, tool, prompt, or model-routing behavior.

## Execution tasks

### Task 1: Record baseline, approved design, and plan

Files: the two documents above.

- [x] Fetch origin and verify `origin/main = 46a69bf3e18f4aaba3505887bd039ca3a7288ffe`; verify the current Stage 4 baseline is its first parent and preserve `.worktrees/`.
- [x] Create the design document before implementation.
- [x] Create this single-agent plan with exact interfaces and verification commands.
- [ ] Commit both documents with `docs: record Stage 5 M5A design and plan`.

Run:

```powershell
git fetch origin
git rev-parse origin/main
git show -s --format='%P' origin/main
git diff --exit-code origin/main^ origin/main -- . ':!docs/superpowers'
```

Expected: origin/main is the locked merge SHA; the parent is the locked Stage 4 SHA; the merge commit contains no unexpected Stage 4 file changes.

### Task 2: Add corpus and corpus contract tests

Files: `knowledge/novacommerce/**`, `tests/knowledge/test_corpus.py`, `scripts/ingest_knowledge_corpus.py`.

- [ ] RED: write tests asserting all required manifest paths exist, metadata is valid, current/history versions are coherent, and there are no duplicate logical versions.
- [ ] Verify RED: `uv run pytest tests/knowledge/test_corpus.py -q` fails because the corpus is absent.
- [ ] GREEN: add realistic internally consistent English NovaCommerce shipping, returns, refunds, warranty, payment, privacy, product-guide, FAQ, and history documents plus a manifest validator/CLI.
- [ ] Verify GREEN: rerun the focused test and `uv run python scripts/ingest_knowledge_corpus.py --check`.
- [ ] Commit `data: add NovaCommerce Stage 5 knowledge corpus`.

### Task 3: Implement parser, normalization, and deterministic chunking with TDD

Files: `src/verbaops/knowledge/parsing.py`, `src/verbaops/knowledge/chunking.py`, `src/verbaops/knowledge/validation.py`, `tests/knowledge/test_parsing.py`, `tests/knowledge/test_chunking.py`, `tests/knowledge/test_validation.py`.

- [ ] RED: add one failing test per behavior: ATX heading levels, Introduction before first heading, Unicode/newline/trailing-whitespace normalization, deterministic source hashes, section-local chunks, 180-token maximum, 30-token same-section overlap, deterministic indexes, and deterministic chunk hashes.
- [ ] Verify RED: `uv run pytest tests/knowledge/test_parsing.py tests/knowledge/test_chunking.py tests/knowledge/test_validation.py -q` fails on missing interfaces.
- [ ] GREEN: implement strict UTF-8/Markdown/size/slug/title/language/date/version validation, canonical normalization, section detection, and whitespace-token chunking with no empty chunks or cross-section merges.
- [ ] Verify GREEN: rerun the focused command and `uv run ruff check src/verbaops/knowledge tests/knowledge`.
- [ ] Commit `feat: add deterministic knowledge parsing and chunking`.

### Task 4: Add security quarantine and domain models

Files: `src/verbaops/knowledge/models.py`, `src/verbaops/knowledge/validation.py`, `tests/knowledge/test_security.py`.

- [ ] RED: test synthetic API/private-key/password/token patterns and suspicious credential/instruction content as quarantine outcomes; test that tenant/customer/role fields in Markdown are ignored and never become metadata.
- [ ] Verify RED: `uv run pytest tests/knowledge/test_security.py -q` fails on missing quarantine behavior.
- [ ] GREEN: add sanitized `ValidationIssue`/quarantine decisions, status enums, immutable domain records, and bounded safe error codes without logging source content.
- [ ] Verify GREEN: rerun security tests and assert logs/API payloads contain no uploaded source.
- [ ] Commit `feat: quarantine unsafe knowledge uploads`.

### Task 5: Add migration and database table contract

Files: `migrations/versions/0004_knowledge_rag_v1.py`, `src/verbaops/knowledge/repository_tables.py`, `migrations/env.py`, `tests/migrations/test_knowledge_migration.py`, `tests/postgres/test_knowledge_schema.py`.

- [ ] RED: write PostgreSQL tests for upgrade/downgrade policy, exact four tables/columns/status constraints, vector dimension 768, HNSW cosine and GIN indexes, required metadata, duplicate document/version rejection, one-active partial index, and tenant predicates.
- [ ] Verify RED: `uv run pytest tests/migrations/test_knowledge_migration.py tests/postgres/test_knowledge_schema.py -m postgres -q` fails because revision 0004/tables are absent.
- [ ] GREEN: add exactly one Alembic revision from 0003 with UUID keys, FKs, required constraints, `VECTOR(768)`, `TSVECTOR`, HNSW cosine index, GIN index, and the partial unique active index. Import tables for metadata without changing earlier migrations.
- [ ] Verify GREEN: with PostgreSQL 16 + pgvector, run `uv run alembic upgrade head`, the schema tests, and `uv run alembic downgrade 0003_evaluation_v1` followed by `uv run alembic upgrade 0004_knowledge_rag_v1` if repository policy requires downgrade tests.
- [ ] Commit `feat: add versioned knowledge PostgreSQL schema`.

### Task 6: Add embedding client and deterministic provider contract

Files: `src/verbaops/knowledge/embeddings.py`, `src/verbaops/llm/**` only where the existing gateway contract requires it, `infra/litellm/config.test.yaml`, `tests/knowledge/test_embeddings.py`, `tests/integration/test_embedding_gateway_contract.py`, `pyproject.toml`, `uv.lock`.

- [ ] RED: test deterministic 768-vector output, malformed response, missing embedding, wrong dimension, and partial batch rejection against a fake OpenAI-compatible response.
- [ ] Verify RED: `uv run pytest tests/knowledge/test_embeddings.py tests/integration/test_embedding_gateway_contract.py -q` fails because the client/provider alias is absent.
- [ ] GREEN: implement `EmbeddingClient` using capability alias `embedding-multilingual`, `/v1/embeddings`, strict response validation, deterministic test-provider support, and no model import in FastAPI.
- [ ] Verify GREEN: rerun the tests with no external credentials and inspect the request to confirm the alias and endpoint.
- [ ] Commit `feat: add provider-free 768-dimensional embedding contract`.

### Task 7: Implement repository/service ingestion and version lifecycle

Files: `src/verbaops/knowledge/repository.py`, `src/verbaops/knowledge/service.py`, `src/verbaops/knowledge/repository_tables.py`, `tests/knowledge/test_service.py`, `tests/postgres/test_knowledge_lifecycle.py`.

- [ ] RED: test queued v1, processing, succeeded/ready persistence; duplicate retries; required metadata/hash persistence; v1 active while v2 processes; failed v2 preserving v1; atomic ready-v2 activation; non-ready/future activation rejection; repeated activation idempotency; cross-tenant generic not-found; and no partial chunks after embedding failure.
- [ ] Verify RED: `uv run pytest tests/knowledge/test_service.py tests/postgres/test_knowledge_lifecycle.py -m postgres -q` fails on absent repository/service methods.
- [ ] GREEN: implement transaction-scoped `ingest_version`, complete-set embedding before inserts, `INSERT ... ON CONFLICT` idempotency, job/version failure/quarantine states, and atomic activation with tenant predicates.
- [ ] Verify GREEN: rerun focused service/PostgreSQL tests and inspect counts after duplicate replay.
- [ ] Commit `feat: persist idempotent knowledge ingestion lifecycle`.

### Task 8: Add Celery/Redis worker transport

Files: `src/verbaops/worker/__init__.py`, `src/verbaops/worker/celery_app.py`, `src/verbaops/knowledge/tasks.py`, `pyproject.toml`, `uv.lock`, `docker-compose.yml`, `tests/worker/test_knowledge_tasks.py`.

- [ ] RED: test queued→processing→succeeded, failed task persistence, task ID correlation, duplicate delivery producing one job/version/chunk set, and completed PostgreSQL state surviving Redis loss.
- [ ] Verify RED: `uv run pytest tests/worker/test_knowledge_tasks.py -q` fails because Celery/task/app are absent.
- [ ] GREEN: add a Python 3.12-compatible Celery dependency, Redis broker configuration, a thin UUID task wrapper, and a Compose `worker` service depending on PostgreSQL migration and Redis health.
- [ ] Verify GREEN: run worker tests, `docker compose config`, and a local provider-free task replay against PostgreSQL/Redis.
- [ ] Commit `feat: add Redis Celery knowledge worker`.

### Task 9: Add tenant-admin API and OpenAPI contract

Files: `src/verbaops/api/routes/knowledge_admin.py`, `src/verbaops/api/app.py`, `src/verbaops/api/dependencies.py`, `src/verbaops/api/lifespan.py`, `tests/api/test_knowledge_admin.py`, `tests/test_openapi_contract.py`.

- [ ] RED: test tenant-admin multipart upload returns 202 with document/version/job IDs; customer/support roles get 403; `tenant_id` input is rejected/ignored; job and activation are tenant-scoped; cross-tenant IDs are generic not-found; and every failure uses the existing `{error:{code,message,request_id}}` envelope.
- [ ] Verify RED: `uv run pytest tests/api/test_knowledge_admin.py tests/test_openapi_contract.py -q` fails because routes and schemas are absent.
- [ ] GREEN: add the three routes with strict multipart/Pydantic validation, `Role.TENANT_ADMIN` authorization, trusted tenant scoping, queued job creation, sanitized job status, and atomic activation metadata. Register the router and dependency overrides without changing existing routes.
- [ ] Verify GREEN: rerun API tests and `uv run python -c "from verbaops.api.app import create_app; from tests.api.conftest import build_settings, build_provider; print(sorted(create_app(settings=build_settings(), auth_provider=build_provider()).openapi()['paths']))"`.
- [ ] Commit `feat: add tenant-admin knowledge API`.

### Task 10: Add CI knowledge contract and local verification wiring

Files: `.github/workflows/ci.yml`, `Makefile`, `tests/test_ci_contract.py`, `tests/knowledge/**`, `tests/postgres/**`, `tests/worker/**`.

- [ ] RED: add a CI contract test asserting a `knowledge-contract` job provisions PostgreSQL + Redis, applies migrations through 0004, validates corpus, and runs provider-free parser/security/schema/service/worker/API tests.
- [ ] Verify RED: `uv run pytest tests/test_ci_contract.py -q` fails because the job is absent.
- [ ] GREEN: add only the new `knowledge-contract` job and a local Make target; keep all existing Stage 4 CI jobs unchanged and provide no external API credentials.
- [ ] Verify GREEN: rerun CI contract tests and run the equivalent local command with disposable PostgreSQL + Redis.
- [ ] Commit `ci: add provider-free knowledge contract`.

### Task 11: Final verification and handoff evidence

Files: `docs/superpowers/reports/2026-08-25-verbaops-stage5-m5a-evidence.md`.

- [ ] Run fresh focused M5A tests, all knowledge PostgreSQL tests, the local knowledge-contract equivalent, `make check`, Ruff, Ruff format check, mypy, pre-commit, `git diff --check`, OpenAPI contract, Docker build, and migration-head verification.
- [ ] Run `git diff --name-only origin/main` and exact Stage 3/4 baseline tests to prove tools, schemas, graph, system prompt, routing, and existing CI behavior are unchanged.
- [ ] Capture schema/index, corpus counts/files, generated chunk count, metadata, version switch, failure preservation, tenant isolation, Celery/Redis/idempotency, deterministic embedding, API/OpenAPI, and quarantine evidence.
- [ ] Push `stage5/m5a-knowledge-ingestion`, open a draft PR, wait for hosted CI, and record every job conclusion and the draft PR URL. Do not merge and do not start M5B.
- [ ] Commit the evidence packet only after all verification commands have fresh exit-0 evidence.

## Final verification command set

```powershell
uv run pytest tests/knowledge -q
uv run pytest tests/postgres/test_knowledge_schema.py tests/postgres/test_knowledge_lifecycle.py -m postgres -q
uv run pytest tests/worker/test_knowledge_tasks.py tests/api/test_knowledge_admin.py tests/test_openapi_contract.py -q
uv run pytest tests/test_ci_contract.py -q
make check
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
uv run pre-commit run --all-files
git diff --check
docker build --target runtime -t verbaops:stage5-m5a .
uv run alembic heads
uv run alembic -c alembic-commerce.ini heads
```

Expected heads are `0004_knowledge_rag_v1` for VerbaOps and `0001_create_commerce_schema` for Commerce.
