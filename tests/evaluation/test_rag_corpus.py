import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from verbaops.evaluation.rag_corpus import RagCorpusError, audit_rag_corpus, load_rag_cases

ROOT = Path(__file__).parents[2]


def test_frozen_rag_corpus_has_exact_release_shape() -> None:
    cases = load_rag_cases(ROOT / "evals/rag/v0.1/questions.jsonl")
    audit = audit_rag_corpus(cases, ROOT)
    assert audit.case_count == 120
    assert audit.split_counts == {"dev": 96, "release_holdout": 24}
    assert audit.category_counts == {
        "shipping": 15,
        "returns": 15,
        "refunds": 12,
        "warranty": 12,
        "payments": 10,
        "privacy": 8,
        "product-guides": 18,
        "faq": 15,
        "no-answer": 15,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda case: {**case, "case_id": "shipping-001"},
        lambda case: {**case, "query": "  " + case["query"].upper() + "  "},
    ],
)
def test_audit_rejects_duplicate_ids_and_normalized_queries(
    mutation: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/rag/v0.1/questions.jsonl").read_text().splitlines()
    ]
    cases[1] = mutation(cases[0])
    with pytest.raises(RagCorpusError, match="duplicate"):
        audit_rag_corpus(cases, ROOT)


def test_audit_rejects_positive_no_answer_and_bad_fact_locator() -> None:
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/rag/v0.1/questions.jsonl").read_text().splitlines()
    ]
    cases[0]["relevance_judgments"] = [
        {
            "document_slug": "missing",
            "document_version": "2026.1",
            "section": "x",
            "chunk_index": 0,
            "relevance_grade": 2,
        }
    ]
    with pytest.raises(RagCorpusError, match="locator"):
        audit_rag_corpus(cases, ROOT)

    no_answer = next(case for case in cases if case["category"] == "no-answer")
    no_answer["relevance_judgments"] = [
        {
            "document_slug": "shipping-policy",
            "document_version": "2026.1",
            "section": "Shipping Policy",
            "chunk_index": 0,
            "relevance_grade": 1,
        }
    ]
    with pytest.raises(RagCorpusError, match="no-answer"):
        audit_rag_corpus(cases, ROOT)
