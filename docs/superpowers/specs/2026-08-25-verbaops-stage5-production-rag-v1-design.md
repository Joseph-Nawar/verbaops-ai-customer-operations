# VerbaOps Stage 5 Production RAG v1 Design

Status: approved and locked for implementation.

## Scope and boundary

Stage 5 uses Option A: the RAG knowledge corpus owns durable company knowledge only—company policies, FAQs, product guides, and support/company knowledge. Live structured commerce truth remains in the existing tools `get_order_status`, `get_shipment_status`, `get_refund_status`, `search_products`, and `list_delivery_slots`. Stage 5 does not add a Commerce tool and does not move live commerce state into the corpus.

M5A implements versioned knowledge and asynchronous ingestion. M5B implements retrieval behavior. M5C is the later integration and quality hardening milestone. M5A does not implement dense query retrieval, PostgreSQL lexical query services, reciprocal-rank fusion (RRF), reranking, cross-encoder serving, a retrieval graph node, customer citations, retrieval confidence thresholds, RAG abstention, Arabic content, write tools, the Stage 6 policy engine/HITL, voice, Langfuse, or the 120-case benchmark runner.

## Knowledge corpus

The committed NovaCommerce corpus is English-only in Stage 5. The data model and parser retain language metadata and remain language-capable; the implementation makes no claim of Arabic support. `knowledge/novacommerce/manifest.json` is authoritative for each document path, slug, title, document type, language, version, effective date, and current/historical intent. Current documents are the active policy/product/FAQ materials; history documents are preserved historical versions and never silently replace current material.

## Ingestion lifecycle

The application-owned pipeline is:

`upload -> validate -> normalize -> section detect -> deterministic section-aware chunk -> metadata/hash -> embed -> store -> READY`.

Uploads are Markdown only, strict UTF-8, at most 1 MiB, non-empty after normalization, and carry a lowercase URL-safe kebab-case slug of at most 64 characters, a safe version of at most 32 characters, a title of at most 200 characters, a valid ISO language tag, and an ISO effective date. Uploaded content cannot supply tenant, customer, principal, role, or other identity fields. Obvious synthetic secrets and suspicious instruction/credential content are quarantined and never activated. Uploaded source is never logged wholesale.

Normalization is deterministic: Unicode is normalized consistently, CRLF/CR becomes LF, trailing whitespace is stripped, pathological blank-line runs are collapsed, and meaningful Markdown headings/text are preserved. ATX headings from `#` through `######` define sections; content before the first heading belongs to `Introduction`. Chunks never cross section boundaries, target at most 180 normalized-whitespace tokens, overlap 30 tokens only within the same section, contain no empty content, and receive deterministic indexes beginning at zero. `source_hash` is SHA-256 over the canonical normalized source; `content_hash` is SHA-256 over canonical normalized chunk content.

## Metadata, versioning, and storage

The VerbaOps `0004_knowledge_rag_v1` migration creates `knowledge_documents`, `knowledge_versions`, `knowledge_chunks`, and `knowledge_ingestion_jobs`. Documents are tenant-scoped by `(tenant_id, slug, language)`. Versions are unique per `(document_id, version)` and use `processing`, `ready`, `active`, `superseded`, `failed`, and `quarantined` statuses. A partial unique index guarantees at most one active version per document. Chunks persist required document/version/section/language/effective-date metadata, deterministic hashes, a required `VECTOR(768)` embedding, and PostgreSQL English `TSVECTOR` search data. PostgreSQL owns job and version state; Redis is only transport.

Creating v2 leaves v1 active while v2 processes and becomes ready. Only an explicit, same-tenant activation transaction changes v1 `active -> superseded` and v2 `ready -> active`. Activation requires `ready`, rejects future effective dates because M5A has no scheduled activation, is idempotent for the already-active same version, and hides cross-tenant identifiers as generic not-found responses. Failure or quarantine leaves the prior active version and usable chunks untouched. No partially embedded version is persisted.

## Embedding boundary

The application owns a focused `EmbeddingClient`; FastAPI does not load a heavyweight model. It calls the existing LiteLLM gateway at the OpenAI-compatible `/v1/embeddings` endpoint using capability alias `embedding-multilingual`, with an expected dimension of 768. Production later uses `multilingual-e5-base`; local TEI serving belongs to M5B. CI extends the deterministic provider path so this alias returns deterministic 768-dimensional vectors. Missing, malformed, partial, or incorrectly dimensioned responses fail ingestion and do not create usable chunks. CI uses no paid provider or external credentials.

## Async transport

Celery uses the existing Redis broker and a worker service in Compose. `src/verbaops/knowledge/tasks.py` is a thin transport wrapper correlated by `ingestion_job_id`; parsing, chunking, embedding, storage, lifecycle, and security behavior remain ordinary testable services. PostgreSQL transitions jobs `queued -> processing -> succeeded|failed|quarantined`. Duplicate task delivery is safe: one logical document version, one job, one chunk set. Redis loss cannot erase completed PostgreSQL state.

## Admin API and security

Tenant admins use `POST /v1/admin/knowledge/documents` multipart fields `file`, `slug`, `title`, `document_type`, `language`, `version`, and `effective_date`; it returns 202 with `document_id`, `version_id`, `ingestion_job_id`, and `status=queued`. `GET /v1/admin/knowledge/ingestions/{ingestion_job_id}` returns sanitized tenant-scoped status. `POST /v1/admin/knowledge/versions/{version_id}/activate` returns activated version metadata. Every route requires `Role.TENANT_ADMIN`; tenant identity comes only from `get_trusted_context().tenant_id`, never from request input. Customer/support roles receive authorization failure, and cross-tenant document/version/job IDs do not reveal existence. Existing request IDs and the structured API error envelope remain in force.

## Retrieval and quality design (later milestones)

M5B will consume active, tenant-scoped chunks using dense vector retrieval and PostgreSQL lexical retrieval, fuse candidates with reciprocal-rank fusion, rerank them with a cross-encoder, and emit source citations. A confidence threshold will support safe abstention when evidence is insufficient. M5C will connect retrieval to the agent boundary and validate the end-to-end behavior with a 120-case RAG benchmark covering policy/FAQ/product-guide questions, version correctness, tenant isolation, citation quality, and abstention. Those components are designed here so the M5A storage metadata and lifecycle are stable, but they are not implemented in M5A.

## Security invariants

Tenant boundaries are enforced from trusted authentication context and database predicates. Source content is treated as untrusted data, never as instructions or identity. Secrets, credentials, prompt-injection-like instructions, and suspicious control content are quarantined. Logs and API responses are sanitized. The active-version partial unique index, atomic activation transaction, strict embedding validation, and no-partial-write transaction are defense-in-depth controls.

## M5 boundaries

- M5A: corpus, validation/normalization/parser/chunker, hashes and metadata, pgvector-backed persistence, version/job lifecycle, deterministic/provider-free embeddings, tenant-admin API, Celery/Redis ingestion transport, and CI knowledge contract.
- M5B: dense and lexical retrieval, RRF, reranking, retrieval citations, confidence threshold, abstention, and the retrieval service contract.
- M5C: agent integration, production retrieval quality, and the 120-case RAG benchmark.
