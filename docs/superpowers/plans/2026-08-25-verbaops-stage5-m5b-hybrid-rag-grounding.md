# Stage 5 M5B — Hybrid Retrieval, Reranking & Grounded Agent Implementation Plan

SINGLE-AGENT execution only.
No subagents.
Human architecture approval already granted.

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution in this session. Do not dispatch subagents or use subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tenant-safe hybrid knowledge retrieval, deterministic RRF fusion, TEI reranking, grounded citation finalization, and LangGraph integration on top of the locked M5A merge.

**Architecture:** Keep Commerce authoritative for live business state and unchanged as five existing read tools. Add retrieval as an application-owned dependency that reads only active, current, tenant-scoped M5A knowledge; persist invocation/candidate/citation audit records in PostgreSQL; pass an untrusted evidence envelope into a new v2 system prompt; finalize and persist citations from database-resolved handles before completing the turn.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic/PostgreSQL/pgvector, PostgreSQL FTS, httpx, Pydantic, LangGraph, LiteLLM/OpenAI-compatible embeddings, TEI reranker HTTP API, pytest, Docker Compose, GitHub Actions.

**Spec:** User-provided Stage 5 M5B brief pasted in the conversation; locked base `ec62c4d8f77837fb05fde27ecbaa9138f76f8926`.

## Global Constraints

- SINGLE-AGENT execution only; never use subagents or subagent-driven-development.
- Human architecture approval already granted; do not repeat brainstorming or request approval.
- Branch is `stage5/m5b-hybrid-rag-grounding`; do not begin M5C or Stage 6.
- RAG owns policies, FAQs, product guides, and company/support knowledge only.
- Live business state remains only in `get_order_status`, `get_shipment_status`, `get_refund_status`, `search_products`, and `list_delivery_slots`; do not modify their schemas or expose RAG as a Commerce tool.
- VerbaOps migration head must be `0005_retrieval_grounding_v1`; Commerce remains `0001_create_commerce_schema`.
- Production embedding model is `intfloat/multilingual-e5-base`, dimension `768`, profile `multilingual-e5-base-v1`; use centralized `query: ` and `passage: ` formatters.
- Dense retrieval uses only compatible-profile, active, effective-today-or-earlier, English, tenant-scoped versions; lexical retrieval uses the same safety filters.
- RRF uses `1 / (60 + rank)`, dense and lexical top 20, deterministic tie-breaking, fused top 20; never add raw dense and lexical scores.
- Reranker is `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, called directly through TEI `POST /rerank` with `raw_scores=false`, validated strictly, and limited to fused top 20/final top 5.
- Retrieval threshold `0.5` is provisional and must not be described as benchmark-calibrated.
- Retrieval/model outage yields no evidence and permits Commerce-tool turns to continue; database or tenant-scope integrity failures may fail the turn.
- Retrieved content is untrusted data and cannot alter identity, tenant, customer, roles, permissions, tool availability, business authority, or tool arguments.
- Citation handles are server-resolved from persisted selected candidates; fabricated handles and assistant-written metadata never become valid public citations.
- Hosted CI must not download Hugging Face models; use deterministic 768-dimensional embeddings and deterministic rerank stubs.
- Preserve M5A corpus, chunking parameters, five Commerce tool schemas/API, Stage 4 artifacts, and M5A ingestion behavior except for recording the new provenance fields on successful M5B ingestion.
- Do not commit credentials, model tokens, floating `latest`/`main` image references, benchmark reports, threshold calibration, Arabic evaluation, write tools, HITL, voice, Langfuse, or LLM judge work.

---

## File map

- Create `migrations/versions/0005_retrieval_grounding_v1.py` for provenance columns and retrieval/citation tables.
- Modify `src/verbaops/knowledge/repository_tables.py`, `src/verbaops/knowledge/models.py`, and `src/verbaops/knowledge/repository.py` for M5B provenance and tenant-safe retrieval persistence primitives.
- Create `src/verbaops/knowledge/profiles.py` for versioned query/passage formatting and model/profile constants.
- Modify `src/verbaops/knowledge/service.py` and `src/verbaops/knowledge/tasks.py` so new successful ingestion stores the M5B provenance fields and passage-formatted embeddings.
- Create `src/verbaops/retrieval/models.py`, `rrf.py`, `reranker.py`, `repository.py`, `service.py`, and `grounding.py` with focused interfaces for retrieval, ranking, evidence, and citation finalization.
- Modify `src/verbaops/agent/context.py`, `state.py`, `graph.py`, `runtime.py`, `versions.py`; create `src/verbaops/agent/prompts/system_v2.txt` and update prompt loading for the v2 trust boundary.
- Modify `src/verbaops/conversations/domain.py`, `repository.py`, `service.py`, and `persistence.py` only where needed to attach atomic assistant citations and return them without N+1 queries.
- Modify `src/verbaops/api/routes/conversations.py` for backward-compatible public citation fields and response rendering.
- Modify `src/verbaops/api/lifespan.py` and dependency composition to construct one retrieval service from the existing database/embedding HTTP client and reranker HTTP client.
- Modify `docker-compose.yml`, `.env.example` if present, and LLM/LiteLLM configuration for the `rag-models` profile, pinned TEI revisions/digest, and `embedding-multilingual` routing.
- Create `scripts/rag_contract.py` or equivalent deterministic contract runner and extend `.github/workflows/ci.yml`, `Makefile`, and CI contract tests with `rag-contract`.
- Add focused unit tests under `tests/retrieval/`, PostgreSQL tests under `tests/postgres/`, agent tests under `tests/agent/`, API tests under `tests/api/`, migration tests under `tests/migrations/`, and deterministic poisoned-evidence fixtures under `tests/support/`.
- Create a real local smoke script under `scripts/` that uses the pinned TEI profile and a fresh test database without changing the committed corpus or threshold.

## Interfaces shared across tasks

```python
RETRIEVAL_VERSION = "knowledge-retrieval-v1"
EMBEDDING_PROFILE = "multilingual-e5-base-v1"
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def format_query(normalized_query: str) -> str: ...
def format_passage(chunk_content: str) -> str: ...


class KnowledgeRetriever(Protocol):
    async def retrieve(
        self, *, agent_run_id: UUID, tenant_id: UUID, query: str, language: str = "en"
    ) -> RetrievalResult: ...


class RerankerClient(Protocol):
    async def rerank(
        self, query: str, candidates: Sequence[RetrievalCandidate]
    ) -> list[RerankScore]: ...


class CitationFinalizer(Protocol):
    def finalize(self, content: str, evidence: Sequence[EvidenceItem]) -> GroundedResponse: ...
```

Each task below consumes only the interfaces named before it and produces the interfaces named for later tasks.

---

### Task 1: Add the M5B schema and repository table definitions

**Files:**
- Create: `migrations/versions/0005_retrieval_grounding_v1.py`
- Modify: `src/verbaops/knowledge/repository_tables.py`
- Modify: `src/verbaops/conversations/persistence.py` only if a shared mapped table is required; do not change existing Commerce tables
- Test: `tests/migrations/test_retrieval_grounding_migration.py`
- Test: `tests/postgres/test_retrieval_schema.py`

**Interfaces:**
- Produces SQL tables/columns for `knowledge_versions.embedding_profile`, `knowledge_versions.embedding_model`, `retrieval_invocations`, `retrieval_candidates`, and `message_citations`.
- Produces SQLAlchemy Core table objects consumed by Tasks 2, 4, 5, and 7.

- [ ] **Step 1: Write the failing migration/schema tests.** Assert the revision is `0005_retrieval_grounding_v1`, down revision is `0004_knowledge_rag_v1`, the Commerce migration is untouched, all required columns/FKs/status checks/indexes exist, `UNIQUE(agent_run_id, sequence)` exists, `UNIQUE(retrieval_invocation_id, chunk_id)` exists, and `UNIQUE(message_id, citation_ordinal)` exists.

- [ ] **Step 2: Run the tests to verify RED.**

  Run: `uv run pytest tests/migrations/test_retrieval_grounding_migration.py tests/postgres/test_retrieval_schema.py -q`

  Expected: failure because revision `0005_retrieval_grounding_v1` and the four new tables do not exist.

- [ ] **Step 3: Implement the migration.** Add the two nullable provenance columns, all three retrieval/citation tables, UUID FKs with the specified cascade behavior, allowed statuses, non-negative counters/latencies, stable snapshot fields, and indexes matching the existing repository conventions. Use `down_revision = "0004_knowledge_rag_v1"`; do not edit `commerce_migrations/versions/0001_create_commerce_schema.py`.

- [ ] **Step 4: Add Core table definitions and run GREEN.** Mirror the migration names/types in `repository_tables.py`, run the focused tests against a fresh pgvector database with `uv run alembic upgrade head`, and assert `uv run alembic heads` reports `0005_retrieval_grounding_v1` while `uv run alembic -c alembic-commerce.ini heads` reports `0001_create_commerce_schema`.

- [ ] **Step 5: Commit.**

  ```text
  git add migrations/versions/0005_retrieval_grounding_v1.py src/verbaops/knowledge/repository_tables.py tests/migrations/test_retrieval_grounding_migration.py tests/postgres/test_retrieval_schema.py
  git commit -m "feat: add retrieval grounding schema"
  ```

### Task 2: Version the M5B embedding profile and persist ingestion provenance

**Files:**
- Create: `src/verbaops/knowledge/profiles.py`
- Modify: `src/verbaops/knowledge/embeddings.py`
- Modify: `src/verbaops/knowledge/models.py`
- Modify: `src/verbaops/knowledge/repository.py`
- Modify: `src/verbaops/knowledge/service.py`
- Modify: `src/verbaops/knowledge/tasks.py`
- Test: `tests/knowledge/test_profiles.py`
- Test: `tests/knowledge/test_embeddings.py`
- Test: `tests/postgres/test_knowledge_lifecycle.py`

**Interfaces:**
- `format_query()` and `format_passage()` are the only application-owned E5 formatting functions.
- `KnowledgeRepository.store_ready_chunks(..., embedding_profile, embedding_model)` records provenance on the version.

- [ ] **Step 1: Write RED tests.** Assert exact `query: ` and `passage: ` output, the production constants, passage formatting during successful ingestion, and persisted `embedding_profile == "multilingual-e5-base-v1"` / `embedding_model == "intfloat/multilingual-e5-base"`.

- [ ] **Step 2: Run the focused tests and confirm the expected missing-profile failures.**

  Run: `uv run pytest tests/knowledge/test_profiles.py tests/knowledge/test_embeddings.py tests/postgres/test_knowledge_lifecycle.py -q`

- [ ] **Step 3: Implement the centralized profile and ingestion wiring.** Keep `EmbeddingClient` provider-neutral; make `KnowledgeService.process_job()` embed `format_passage(draft.content)` and pass the profile/model into the successful storage transaction. Existing M5A/null-profile rows remain valid but are not made dense-compatible by backfill.

- [ ] **Step 4: Run GREEN and verify M5A compatibility.** Run the focused tests and the existing knowledge/worker suites. Confirm no corpus file, chunk size, parser, or M5A migration changed.

- [ ] **Step 5: Commit.**

  ```text
  git add src/verbaops/knowledge/profiles.py src/verbaops/knowledge/embeddings.py src/verbaops/knowledge/models.py src/verbaops/knowledge/repository.py src/verbaops/knowledge/service.py src/verbaops/knowledge/tasks.py tests/knowledge/test_profiles.py tests/knowledge/test_embeddings.py tests/postgres/test_knowledge_lifecycle.py
  git commit -m "feat: version knowledge embedding profile"
  ```

### Task 3: Implement deterministic ranking and strict TEI reranking clients

**Files:**
- Create: `src/verbaops/retrieval/__init__.py`
- Create: `src/verbaops/retrieval/models.py`
- Create: `src/verbaops/retrieval/rrf.py`
- Create: `src/verbaops/retrieval/reranker.py`
- Test: `tests/retrieval/test_profiles_and_ranking.py`
- Test: `tests/retrieval/test_reranker.py`

**Interfaces:**
- `DenseHit`, `LexicalHit`, `FusedCandidate`, `RerankScore`, and `RetrievalResult` are immutable typed records.
- `reciprocal_rank_fusion(dense, lexical, k=60, limit=20)` deduplicates by UUID and sorts by descending score then stable `chunk_id`.
- `RerankerClient` posts `{"query": query, "texts": [...], "raw_scores": false}` to `/rerank`, and rejects non-2xx, malformed, partial, duplicate, out-of-range, non-finite, or repeated-index responses.

- [ ] **Step 1: Write RED unit tests.** Cover exact E5 formatting, dense cosine-to-score conversion, exact RRF math (`1/61`, `1/62`, etc.), tie ordering, reranker request shape, `raw_scores=false`, every malformed response class, and finite unique index validation.

- [ ] **Step 2: Run unit tests and verify RED.**

  Run: `uv run pytest tests/retrieval/test_profiles_and_ranking.py tests/retrieval/test_reranker.py -q`

- [ ] **Step 3: Implement the smallest pure ranking functions and typed TEI parser.** Never combine raw vector similarity and FTS rank scores numerically; carry each stage’s rank/score separately for persistence.

- [ ] **Step 4: Run GREEN and refactor only after all tests pass.**

- [ ] **Step 5: Commit.**

  ```text
  git add src/verbaops/retrieval tests/retrieval
  git commit -m "feat: add hybrid ranking and reranker client"
  ```

### Task 4: Implement tenant-safe dense and lexical retrieval

**Files:**
- Create: `src/verbaops/retrieval/repository.py`
- Modify: `src/verbaops/knowledge/repository.py` only for shared version/chunk row conversion helpers
- Test: `tests/postgres/test_retrieval_repository.py`

**Interfaces:**
- `RetrievalRepository.search_dense(session, tenant_id, vector, profile, language, limit=20)` returns `DenseHit` rows.
- `RetrievalRepository.search_lexical(session, tenant_id, query, language, limit=20)` returns `LexicalHit` rows.
- Both methods filter `tenant_id`, `knowledge_versions.status = 'active'`, `effective_date <= CURRENT_DATE`, `language = 'en'`, and document/version/chunk joins; dense additionally filters the exact embedding profile.

- [ ] **Step 1: Write RED PostgreSQL fixtures/tests.** Seed two tenants, active/current and excluded versions for each tenant, READY/SUPERSEDED/FAILED/QUARANTINED versions, future-effective versions, compatible and incompatible profiles, and chunks with known vectors/search vectors. Assert every mandatory exclusion for both dense and lexical search.

- [ ] **Step 2: Run the PostgreSQL test to verify RED.**

  Run with a fresh pgvector database: `uv run pytest tests/postgres/test_retrieval_repository.py -m postgres -q`

- [ ] **Step 3: Implement parameterized SQLAlchemy queries.** Use pgvector cosine distance for dense ranking and `websearch_to_tsquery('english', :query)` with `ts_rank_cd` for lexical ranking. Select only the metadata required by later evidence envelopes; never interpolate tenant/query strings into SQL.

- [ ] **Step 4: Run GREEN and inspect query results.** Prove no cross-tenant, non-active, future, incompatible-profile, READY, SUPERSEDED, FAILED, or QUARANTINED chunk appears.

- [ ] **Step 5: Commit.**

  ```text
  git add src/verbaops/retrieval/repository.py src/verbaops/knowledge/repository.py tests/postgres/test_retrieval_repository.py
  git commit -m "feat: add tenant-safe hybrid retrieval queries"
  ```

### Task 5: Persist retrieval traces and implement the retrieval service

**Files:**
- Create: `src/verbaops/retrieval/service.py`
- Modify: `src/verbaops/retrieval/models.py`
- Modify: `src/verbaops/retrieval/repository.py`
- Test: `tests/retrieval/test_retrieval_service.py`
- Test: `tests/postgres/test_retrieval_persistence.py`

**Interfaces:**
- `RetrievalService.retrieve(...)` runs dense query embedding with `format_query`, dense/lexical top 20, RRF top 20, reranking top 5, and threshold handling.
- Persist one `retrieval_invocations` row per `agent_run_id`/sequence and all stage scores/ranks in `retrieval_candidates`.
- Success returns selected evidence; insufficient returns `status="insufficient"` and empty evidence; provider outage returns `status="unavailable"`/`failed` internally and empty evidence without fabricated content.

- [ ] **Step 1: Write RED service and persistence tests.** Assert query formatting, defaults, counts, trace status, model fields, latency, candidate score/rank persistence, `top_score`, threshold `0.5`, no evidence on unavailable embedding/reranker, and no duplicate invocation for a sequence.

- [ ] **Step 2: Run focused tests and confirm RED.**

  Run: `uv run pytest tests/retrieval/test_retrieval_service.py tests/postgres/test_retrieval_persistence.py -m "not postgres" -q`; then run the PostgreSQL test with `-m postgres`.

- [ ] **Step 3: Implement the service with short database transactions.** External embedding/reranking occurs outside database transactions; persistence is performed in one short transaction after ranking. Treat only database/tenant-scope integrity errors as turn-fatal; map model/network protocol failures to no-evidence retrieval outcomes.

- [ ] **Step 4: Run GREEN and verify exact persisted counts.**

- [ ] **Step 5: Commit.**

  ```text
  git add src/verbaops/retrieval/service.py src/verbaops/retrieval/models.py src/verbaops/retrieval/repository.py tests/retrieval/test_retrieval_service.py tests/postgres/test_retrieval_persistence.py
  git commit -m "feat: persist retrieval traces and evidence"
  ```

### Task 6: Add citation parsing, safe grounding fallback, and atomic citation persistence

**Files:**
- Create: `src/verbaops/retrieval/grounding.py`
- Modify: `src/verbaops/conversations/domain.py`
- Modify: `src/verbaops/conversations/repository.py`
- Modify: `src/verbaops/conversations/service.py`
- Test: `tests/retrieval/test_grounding.py`
- Test: `tests/postgres/test_citations.py`

**Interfaces:**
- `EvidenceItem` contains opaque handle plus database metadata and untrusted content.
- `CitationFinalizer.finalize()` accepts only supplied handles, deduplicates them in first-use order, replaces valid handles with `[1]`, `[2]`, etc., and applies a deterministic safe fallback for unknown handles.
- `ConversationService.complete_turn(..., citations=...)` writes the assistant message and `message_citations` snapshot in the same transaction and returns citation records.

- [ ] **Step 1: Write RED unit tests.** Cover valid handles, duplicate handles, fabricated handles, handles in prose metadata, no-citation responses, malformed syntax, and fallback content that does not claim unsupported evidence.

- [ ] **Step 2: Write RED PostgreSQL tests.** Assert citation metadata is resolved from selected candidate/version/document rows rather than assistant prose, `UNIQUE(message_id, citation_ordinal)` is honored, assistant completion plus citations are atomic, and GET-style page loading returns citations without one query per message.

- [ ] **Step 3: Run tests and verify RED.**

  Run: `uv run pytest tests/retrieval/test_grounding.py tests/postgres/test_citations.py -q`.

- [ ] **Step 4: Implement finalization and persistence.** Strip/replace only server-recognized handles, never trust model-generated document/title/version/section/effective-date text, and abort completion if citation persistence fails.

- [ ] **Step 5: Run GREEN and commit.**

  ```text
  git add src/verbaops/retrieval/grounding.py src/verbaops/conversations/domain.py src/verbaops/conversations/repository.py src/verbaops/conversations/service.py tests/retrieval/test_grounding.py tests/postgres/test_citations.py
  git commit -m "feat: finalize and persist grounded citations"
  ```

### Task 7: Integrate retrieval into the v2 grounded LangGraph agent

**Files:**
- Modify: `src/verbaops/agent/context.py`
- Modify: `src/verbaops/agent/state.py`
- Modify: `src/verbaops/agent/graph.py`
- Modify: `src/verbaops/agent/runtime.py`
- Modify: `src/verbaops/agent/versions.py`
- Create: `src/verbaops/agent/prompts/system_v2.txt`
- Modify: `src/verbaops/agent/prompts/__init__.py`
- Test: `tests/agent/test_retrieval_graph.py`
- Test: `tests/agent/test_grounding_security.py`

**Interfaces:**
- `AgentContext` receives trusted `retrieval_service` and `citation_finalizer` dependencies.
- `AgentState` adds only `knowledge_status`, `knowledge_evidence`, and `retrieval_invocation_id`.
- Graph topology becomes `START → retrieve_knowledge → agent → validate_tool_calls → execute_tools → agent → finalize_grounding → END`.
- Set `GRAPH_VERSION = "text-agent-v2"`, `PROMPT_VERSION = "text-agent-system-v2"`, and retain `TOOL_SCHEMA_VERSION = "commerce-read-tools-v1"`.

- [ ] **Step 1: Write RED graph/security tests.** Assert retrieval runs before the first model call using the current/latest user message, sufficient evidence reaches the model, insufficient/outage states contain no evidence, Commerce tools remain available during model outage, and poisoned text cannot alter trusted identity, customer ID, tool registry, or create a write tool.

- [ ] **Step 2: Run the agent tests and verify RED.**

  Run: `uv run pytest tests/agent/test_retrieval_graph.py tests/agent/test_grounding_security.py -q`

- [ ] **Step 3: Add v2 prompt and graph nodes.** The prompt must explicitly distinguish authoritative Commerce facts from retrieved policy/FAQ/guide claims, label retrieved content untrusted, ignore embedded instructions, preserve trusted identity/tenant/customer/roles/permissions/tools, require supplied `[[K#]]` handles, prohibit invented handles, and state inability to verify when knowledge is insufficient/unavailable.

- [ ] **Step 4: Preserve existing validation/execution behavior.** Route all existing tool calls through the unchanged registry and execution functions; only add retrieval context and final grounding. Run the complete existing agent unit suite plus the new tests.

- [ ] **Step 5: Commit.**

  ```text
  git add src/verbaops/agent tests/agent
  git commit -m "feat: integrate grounded retrieval into agent graph"
  ```

### Task 8: Expose backward-compatible citations through the conversation API

**Files:**
- Modify: `src/verbaops/api/routes/conversations.py`
- Modify: `src/verbaops/conversations/domain.py`
- Test: `tests/api/test_conversations_m5b.py`
- Test: `tests/test_openapi_contract.py` if the normalized contract changes
- Optional UI only if straightforward: `apps/web/...` existing chat message component and its tests

**Interfaces:**
- Public citation shape is `{number, document, section, version, effective_date}`.
- `POST /v1/conversations/{conversation_id}/messages` includes `assistant_message.citations`.
- `GET /v1/conversations/{conversation_id}` includes citations on assistant messages loaded in the same bounded page query.
- Existing clients can ignore the new field; no Commerce API/schema changes.

- [ ] **Step 1: Write RED API tests.** Assert real DB-resolved citation metadata in POST, historical reproduction in GET, fabricated assistant metadata is absent/rejected, and no-citation messages serialize an empty/default-compatible field.

- [ ] **Step 2: Run API tests to verify RED.**

  Run: `uv run pytest tests/api/test_conversations_m5b.py -q`.

- [ ] **Step 3: Implement response models and mapping.** Batch-load citations for the message page by message IDs or join them in the existing page query; do not add per-message queries. Keep response fields public and omit internal IDs unless the existing contract needs them.

- [ ] **Step 4: Run GREEN and validate OpenAPI.** Run `make commerce-contract-check` and `make openapi-contract`/the repository’s existing OpenAPI contract target as applicable; verify only VerbaOps conversation schemas changed.

- [ ] **Step 5: Commit.**

  ```text
  git add src/verbaops/api/routes/conversations.py src/verbaops/conversations tests/api/test_conversations_m5b.py tests/test_openapi_contract.py apps/web
  git commit -m "feat: expose grounded conversation citations"
  ```

### Task 9: Compose real TEI services and wire runtime dependencies

**Files:**
- Modify: `docker-compose.yml`
- Modify: `src/verbaops/api/lifespan.py`
- Modify: `src/verbaops/config/settings.py`
- Modify: `src/verbaops/knowledge/embeddings.py` only for the configured LiteLLM alias path if required
- Create/modify: `litellm_config.yaml` or the repository’s existing LiteLLM configuration location
- Test: `tests/test_compose_contract.py`
- Test: `tests/config/test_rag_settings.py`

**Interfaces:**
- `rag-models` profile contains `tei-embedding` and `tei-reranker` with immutable image references/digests and immutable Hugging Face model revisions.
- LiteLLM alias `embedding-multilingual` points to the embedding TEI OpenAI-compatible `/v1/embeddings` endpoint.
- `RerankerClient` points directly to reranker TEI `/rerank` without credentials.

- [ ] **Step 1: Resolve and record immutable revisions.** Query official Hugging Face model metadata for `intfloat/multilingual-e5-base` and `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, and use an immutable TEI image tag plus digest from the official TEI image source. Record exact revisions in Compose/config tests and the final handoff; never use `latest` or `main`.

- [ ] **Step 2: Write RED Compose/config contract tests.** Assert the profile, services, model revisions, image digests, ports/health checks, alias endpoint, absence of real secrets, and normal Compose behavior when `rag-models` is not selected.

- [ ] **Step 3: Implement runtime composition.** Create one reranker HTTP client, reuse the existing HTTP lifecycle safely, construct `RetrievalService`, and inject it into `AgentRuntime`/`AgentContext`. Ensure partial startup cleanup closes every client.

- [ ] **Step 4: Run GREEN.** Execute `docker compose --profile rag-models config --quiet` and the focused configuration tests.

- [ ] **Step 5: Commit.**

  ```text
  git add docker-compose.yml src/verbaops/api/lifespan.py src/verbaops/config/settings.py src/verbaops/knowledge/embeddings.py litellm_config.yaml tests/test_compose_contract.py tests/config/test_rag_settings.py
  git commit -m "feat: add pinned local rag model profile"
  ```

### Task 10: Add deterministic provider-free RAG contract and security coverage

**Files:**
- Create: `scripts/run_rag_contract.py`
- Modify: `scripts/llm_test_provider.py` for deterministic 768-d embeddings and rerank responses
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_knowledge_ci_contract.py` or create `tests/test_rag_ci_contract.py`
- Create: `tests/retrieval/test_rag_contract.py`
- Create: poisoned-document fixture under `tests/support/`

**Interfaces:**
- `make rag-contract` runs PostgreSQL-backed retrieval/grounding/graph/API behavior without downloading Hugging Face models or requiring external credentials.
- Hosted `rag-contract` installs pinned dependencies, starts PostgreSQL, applies migrations, runs the deterministic contract, and has no model-download step or secret environment.

- [ ] **Step 1: Write RED contract tests.** Cover dense, lexical, RRF, rerank, tenant/current/profile filters, trace persistence, citation mapping/fallback, LangGraph order, poisoned evidence, API citations, no secret logging, and Commerce authority.

- [ ] **Step 2: Run the contract and CI contract tests to verify RED.**

  Run: `uv run pytest tests/retrieval/test_rag_contract.py tests/test_rag_ci_contract.py -q`.

- [ ] **Step 3: Extend deterministic stubs.** Return stable 768-dimensional vectors based on formatted input and deterministic rerank scores based on query/text content, with strict TEI-shaped responses. Do not make the stub resemble a provider credential or download a model.

- [ ] **Step 4: Add the CI job and run GREEN.** Keep the existing `knowledge-contract`, `agent-acceptance`, Commerce, evaluation, and Stage 4 jobs intact; add an independent `rag-contract` job using PostgreSQL and no HF network/model setup.

- [ ] **Step 5: Commit.**

  ```text
  git add scripts/run_rag_contract.py scripts/llm_test_provider.py Makefile .github/workflows/ci.yml tests/test_knowledge_ci_contract.py tests/test_rag_ci_contract.py tests/retrieval/test_rag_contract.py tests/support
  git commit -m "test: add provider-free rag contract"
  ```

### Task 11: Add real local TEI smoke without threshold tuning

**Files:**
- Create: `scripts/run_rag_tei_smoke.py`
- Create: `docs/superpowers/evidence/2026-08-25-verbaops-stage5-m5b-tei-smoke.md`
- Test: `tests/test_rag_smoke_contract.py`

**Interfaces:**
- The smoke script accepts a fresh database URL/profile, ingests the committed NovaCommerce corpus through the M5B passage profile, and reports retrieval/rerank outcomes without modifying corpus or threshold configuration.

- [ ] **Step 1: Write the smoke contract test.** Assert the script names all eight required checks: return policy, warranty, lexical phrase/number, hybrid candidates, reranked top five, cross-tenant zero, superseded exclusion, and honest unanswerable behavior.

- [ ] **Step 2: Run the contract test and verify RED.**

  Run: `uv run pytest tests/test_rag_smoke_contract.py -q`.

- [ ] **Step 3: Implement the smoke runner.** Start/target the pinned `rag-models` profile, create a disposable database, run migrations, ingest the committed corpus with `passage: ` formatting and provenance, activate current versions, run the queries, and emit only non-secret evidence summaries.

- [ ] **Step 4: Execute the real smoke and record honest results.** Run it with the pinned models. If the provisional `0.5` threshold accepts the unanswerable query, record that behavior rather than tuning it; calibration remains M5C.

- [ ] **Step 5: Commit the smoke tooling/evidence.**

  ```text
  git add scripts/run_rag_tei_smoke.py tests/test_rag_smoke_contract.py docs/superpowers/evidence/2026-08-25-verbaops-stage5-m5b-tei-smoke.md
  git commit -m "test: add real local rag smoke"
  ```

### Task 12: Full verification, preservation audit, push, and hosted CI

**Files:**
- Modify only test/doc evidence files if verification reveals a concrete defect; never weaken an assertion to make a test pass.

- [ ] **Step 1: Run focused suites.**

  ```text
  uv run pytest tests/retrieval -q
  uv run pytest tests/postgres -m postgres -q
  uv run pytest tests/agent -q
  uv run pytest tests/api/test_conversations_m5b.py tests/api/test_conversations_m3e.py -q
  ```

- [ ] **Step 2: Run contracts and existing suites.**

  ```text
  make rag-contract
  make knowledge-contract
  make check
  make commerce-contract-check
  make openapi-contract
  ```

- [ ] **Step 3: Run independent quality checks.** Run Ruff, Ruff format, mypy, pre-commit, and `git diff --check`; if UI changed, run web lint/typecheck/test/build/smoke.

- [ ] **Step 4: Verify Docker and migration heads.** Run `docker compose --profile rag-models config --quiet`, `docker build --target runtime -t verbaops:stage5-m5b .`, `uv run alembic heads`, and `uv run alembic -c alembic-commerce.ini heads`.

- [ ] **Step 5: Audit locked artifacts.** Compare against `ec62c4d8…` and prove unchanged: Stage 4 baseline artifacts, five Commerce tool definitions/schemas/API, M5A corpus manifest/content, M5A chunking parameters, and no credentials/model secrets in Git or build artifacts. Confirm no M5C or Stage 6 files/work were introduced.

- [ ] **Step 6: Review the full diff and commit any final verification-only corrections.** Ensure every production behavior had a prior RED test and every required security exclusion is asserted.

- [ ] **Step 7: Push and open the draft PR.**

  ```text
  git push -u origin stage5/m5b-hybrid-rag-grounding
  gh pr create --draft --base main --head stage5/m5b-hybrid-rag-grounding --title "Stage 5 M5B: hybrid retrieval and grounded agent" --body-file docs/superpowers/evidence/2026-08-25-verbaops-stage5-m5b-tei-smoke.md
  ```

- [ ] **Step 8: Wait for fresh hosted CI.** Record the run ID and every job conclusion. Do not merge and do not start M5C.

## Spec coverage self-review

- Migration/provenance/retrieval/citation schema: Task 1.
- Versioned E5 profile and M5B ingestion provenance: Task 2.
- Dense/lexical filtering, RRF, reranking and typed protocol validation: Tasks 3–5.
- Retrieval outage, threshold abstention, trace persistence, and short transactions: Task 5.
- LangGraph topology, v2 prompt, trusted context, and poisoned-data boundary: Task 7.
- Citation parsing, DB snapshot resolution, fallback, atomic persistence, and API compatibility: Tasks 6 and 8.
- Pinned local TEI profile and LiteLLM alias: Task 9.
- Provider-free CI, deterministic stubs, and mandatory security coverage: Task 10.
- Real TEI smoke and honest provisional-threshold reporting: Task 11.
- Full verification, unchanged-boundary audit, Docker, hosted CI, draft PR, and handoff evidence: Task 12.

No benchmark calibration, Arabic evaluation, write tools, HITL, Stage 6, or M5C work is included.
