"""Deterministic golden-corpus auditing tests."""

from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from verbaops.evaluation.corpus import CorpusAuditError, CorpusManifest, audit_corpus
from verbaops.evaluation.models import ConversationTurn, EvaluationCase

CUSTOMER_ID = UUID("d77809e8-6d3b-5792-9128-ff2bc88bc955")
ORDER_ID = UUID("54d93c0f-951e-5d74-afdd-80d33d4c8c95")
SCENARIO_MANIFEST = {"scenario_ids": {"customer_primary": str(CUSTOMER_ID), "order_cancellable": str(ORDER_ID)}}


def manifest(**overrides: Any) -> CorpusManifest:
    data: dict[str, Any] = {
        "dataset_version": "text-agent-v0.1",
        "language": "en",
        "expected_case_count": 1,
        "split_counts": {"dev": 1, "release_holdout": 0},
        "category_counts": {
            "order-status": 1,
            "shipment-status": 0,
            "refund-status": 0,
            "product-search": 0,
            "delivery-slots": 0,
            "missing-ambiguous-identifiers": 0,
            "unsupported-write": 0,
            "safety-injection-identity-cross-customer": 0,
            "benign-no-tool": 0,
        },
        "approved_tools": [
            "get_order_status",
            "get_shipment_status",
            "get_refund_status",
            "search_products",
            "list_delivery_slots",
        ],
        "scenario_manifest": "tests/acceptance/fixtures/novacommerce-scenarios.json",
    }
    data.update(overrides)
    return CorpusManifest.model_validate(data)


def case(**overrides: Any) -> EvaluationCase:
    data: dict[str, Any] = {
        "case_id": "case-001",
        "dataset_version": "text-agent-v0.1",
        "split": "dev",
        "language": "en",
        "category": "order-status",
        "customer_id": str(CUSTOMER_ID),
        "conversation": [{"role": "user", "content": "What is the status of my order?"}],
        "expected_tool": "get_order_status",
        "expected_arguments": {"order_id": str(ORDER_ID)},
        "expected_outcome": {"kind": "grounded_tool_answer", "authoritative_facts": {"status": "processing"}},
        "requires_confirmation": False,
        "forbidden_actions": ["write"],
        "scenario_ids": [str(ORDER_ID)],
    }
    data.update(overrides)
    return EvaluationCase.model_validate(data)


def test_auditor_accepts_valid_case_and_reports_counts() -> None:
    result = audit_corpus(manifest(), (case(),), SCENARIO_MANIFEST)
    assert result.case_count == 1
    assert result.split_counts == {"dev": 1, "release_holdout": 0}
    assert result.category_counts["order-status"] == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"dataset_version": "text-agent-v0.2"}, "dataset_version"),
        ({"language": "fr"}, "language"),
        ({"category": "unknown"}, "category"),
        ({"expected_tool": "cancel_order"}, "tool"),
        ({"expected_arguments": {"customer_id": str(CUSTOMER_ID)}}, "identity"),
        ({"expected_arguments": {"order_id": "not-a-uuid"}}, "arguments"),
        ({"scenario_ids": ["not-a-uuid"]}, "scenario"),
    ],
)
def test_auditor_rejects_invalid_case(changes: dict[str, Any], message: str) -> None:
    if "conversation" in changes:
        changes = {"conversation": tuple(ConversationTurn.model_validate(turn) for turn in changes["conversation"])}
    invalid = case().model_copy(update=changes)
    with pytest.raises(CorpusAuditError, match=message):
        audit_corpus(manifest(), (invalid,), SCENARIO_MANIFEST)


def test_auditor_rejects_duplicate_case_id() -> None:
    duplicate = case(case_id="case-001", conversation=({"role": "user", "content": "Another order question?"},))
    with pytest.raises(CorpusAuditError, match="duplicate"):
        audit_corpus(manifest(expected_case_count=2, split_counts={"dev": 2, "release_holdout": 0}), (case(), duplicate), SCENARIO_MANIFEST)


def test_auditor_rejects_duplicate_normalized_prompt() -> None:
    duplicate = case(case_id="case-002", conversation=({"role": "user", "content": "WHAT IS THE STATUS OF MY ORDER?"},))
    with pytest.raises(CorpusAuditError, match="duplicate prompt"):
        audit_corpus(manifest(expected_case_count=2, split_counts={"dev": 2, "release_holdout": 0}), (case(), duplicate), SCENARIO_MANIFEST)


def test_auditor_rejects_confirmation_and_wrong_counts() -> None:
    invalid = case().model_copy(update={"requires_confirmation": True})
    with pytest.raises(CorpusAuditError, match="confirmation"):
        audit_corpus(manifest(), (invalid,), SCENARIO_MANIFEST)

    with pytest.raises(CorpusAuditError, match="case count"):
        audit_corpus(manifest(expected_case_count=2), (case(),), SCENARIO_MANIFEST)


def test_full_corpus_has_exact_contract() -> None:
    import json

    from verbaops.evaluation.cases import load_cases

    root = Path(__file__).parents[2]
    cases = load_cases(root / "evals/agent/v0.1/cases.jsonl")
    loaded_manifest = CorpusManifest.model_validate(
        json.loads((root / "evals/agent/v0.1/manifest.json").read_text(encoding="utf-8"))
    )
    scenario_manifest = json.loads(
        (root / "tests/acceptance/fixtures/novacommerce-scenarios.json").read_text(encoding="utf-8")
    )
    result = audit_corpus(loaded_manifest, cases, scenario_manifest)
    assert result.case_count == 120
    assert result.split_counts == {"dev": 96, "release_holdout": 24}
    assert Counter(result.category_counts) == Counter(loaded_manifest.category_counts)
    assert len(result.case_ids) == len(set(result.case_ids)) == 120
