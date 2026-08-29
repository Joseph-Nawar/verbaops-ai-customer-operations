import re
from pathlib import Path


def test_rag_contract_is_a_hosted_postgres_schema_0005_job() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    match = re.search(r"(?ms)^  rag-contract:\n(?P<body>.*?)(?=^  [a-z0-9-]+:|\Z)", workflow)
    assert match is not None
    job = match.group("body")

    assert "pgvector/pgvector:0.8.6-pg16-bookworm" in job
    assert "uv run alembic upgrade 0005_retrieval_grounding_v1" in job
    assert "make rag-contract" in job
    assert "OPENAI_API_KEY" not in job
    assert "HF_TOKEN" not in job
    assert "huggingface" not in job.lower()


def test_rag_contract_make_target_covers_provider_free_m5b_paths() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    target = makefile[makefile.index("rag-contract:\n") : makefile.index("\nagent-acceptance:")]

    assert "require_test_database.py" in target
    assert "0005_retrieval_grounding_v1" in target
    assert "tests/postgres/m5b" in target
    for path in (
        "tests/retrieval",
        "tests/agent/test_retrieval_graph.py",
        "tests/agent/test_grounding_security.py",
        "tests/api/test_conversations_m5b.py",
    ):
        assert path in target
