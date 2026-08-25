from pathlib import Path


def test_knowledge_contract_ci_job_is_provider_free_and_has_postgres_redis() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    job = workflow[workflow.index("  knowledge-contract:") :]
    assert "name: knowledge-contract" in job
    assert "pgvector/pgvector:0.8.6-pg16-bookworm" in job
    assert "redis:8.2.8-bookworm" in job
    assert "uv run alembic upgrade 0004_knowledge_rag_v1" in job
    assert "scripts/ingest_knowledge_corpus.py --check" in job
    assert "tests/knowledge" in job
    assert "tests/postgres" in job
    assert 'tests/worker/test_knowledge_tasks.py -m "not llm_gateway_contract" -q' in job
    assert "OPENAI_API_KEY" not in job
    assert "LITELLM_MASTER_KEY" not in job
