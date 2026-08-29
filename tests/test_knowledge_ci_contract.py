import re
from pathlib import Path


def test_knowledge_contract_ci_job_is_provider_free_and_has_postgres_redis() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    match = re.search(r"(?ms)^  knowledge-contract:\n(?P<body>.*?)(?=^  [a-z0-9-]+:|\Z)", workflow)
    assert match is not None
    job = match.group("body")
    assert "name: knowledge-contract" in job
    assert "pgvector/pgvector:0.8.6-pg16-bookworm" in job
    assert "redis:8.2.8-bookworm" in job
    assert "uv run alembic upgrade 0004_knowledge_rag_v1" in job
    assert "scripts/ingest_knowledge_corpus.py --check" in job
    assert "tests/knowledge" in job
    assert "tests/postgres/m5a" in job
    assert 'tests/worker/test_knowledge_tasks.py -m "not llm_gateway_contract" -q' in job
    assert "message_citations" not in job
    assert "retrieval_candidates" not in job
    assert "retrieval_invocations" not in job
    assert "0005_retrieval_grounding_v1" not in job
    assert "OPENAI_API_KEY" not in job
    assert "LITELLM_MASTER_KEY" not in job
