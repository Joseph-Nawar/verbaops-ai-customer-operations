from pathlib import Path

from verbaops.evaluation.rag_corpus import audit_rag_corpus, load_rag_cases


def test_provider_free_rag_evaluation_contract() -> None:
    root = Path(__file__).parents[2]
    cases = load_rag_cases(root / "evals/rag/v0.1/questions.jsonl")
    audit = audit_rag_corpus(cases, root)
    assert audit.dataset_version == "rag-v0.1"
    assert audit.knowledge_manifest_sha256
