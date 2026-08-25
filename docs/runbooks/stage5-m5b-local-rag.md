# Stage 5 M5B local RAG profile

The `rag-models` Compose profile runs the pinned CPU Text Embeddings Inference
services and a local LiteLLM bridge for the existing `embedding-multilingual`
alias. The application calls the TEI reranker directly.

Start the profile:

```powershell
docker compose --profile rag-models up -d tei-embedding tei-reranker rag-llm-gateway
```

For application processes running on the host, use:

```text
VERBAOPS_LLM__BASE_URL=http://localhost:14000/v1
VERBAOPS_RAG__RERANKER_URL=http://localhost:8082
```

For the `api` and `worker` Compose services, use the service DNS names instead:

```text
VERBAOPS_LLM__BASE_URL=http://rag-llm-gateway:4000/v1
VERBAOPS_RAG__RERANKER_URL=http://tei-reranker:80
```

The first run downloads the pinned public model revisions into named Docker
volumes. No Hugging Face token or provider credential is needed.
