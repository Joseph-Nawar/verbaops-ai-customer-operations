from verbaops.evaluation.rag_metrics import (
    citation_precision,
    grounded_fact_score,
    mean_reciprocal_rank,
    ndcg_at_k,
    recall_at_k,
)


def test_rag_metrics_use_graded_stable_locators() -> None:
    judgments = {"a": 2, "b": 1, "c": 0}
    assert recall_at_k(["b", "x", "a"], judgments, 1) == 0.5
    assert recall_at_k(["b", "x", "a"], judgments, 5) == 1.0
    assert mean_reciprocal_rank(["x", "b", "a"], judgments) == 0.5
    assert ndcg_at_k(["b", "a", "x"], judgments, 5) == 0.7967075809905066


def test_citation_precision_and_grounded_fact_score_are_deterministic() -> None:
    judgments = {"a": 2, "b": 1, "c": 0}
    assert citation_precision(["a", "c"], judgments).as_dict() == {
        "numerator": 1,
        "denominator": 2,
        "value": 0.5,
    }
    result = grounded_fact_score(
        "The return window is 30 days and returns need packaging.",
        [
            {"fact_id": "window", "aliases": ["30 days"], "supporting_locators": ["a"]},
            {"fact_id": "packaging", "aliases": ["packaging"], "supporting_locators": ["b"]},
        ],
        ["a"],
    )
    assert result.recognized == 2
    assert result.supported == 1
    assert result.unsupported == 1


def test_empty_denominators_are_explicitly_not_applicable() -> None:
    assert recall_at_k([], {}, 5) is None
    assert citation_precision([], {}).as_dict() == {
        "numerator": 0,
        "denominator": 0,
        "value": None,
    }
