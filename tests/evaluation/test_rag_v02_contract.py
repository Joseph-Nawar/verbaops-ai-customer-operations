"""Provider-free M5D-A corpus, guard, plan, and immutability contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from verbaops.evaluation.rag_v02 import (
    RagV02Error,
    audit_rag_v02,
    guard_rag_v02_split,
    load_rag_v02_cases,
    validate_experiment_plan,
)

ROOT = Path(__file__).resolve().parents[2]
V02 = ROOT / "evals/rag/v0.2"


def _immutable_sha256(path: Path) -> str:
    """Hash canonical text content consistently across LF and CRLF checkouts."""

    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _cases() -> list[dict[str, object]]:
    return [case.model_dump(mode="json") for case in load_rag_v02_cases(V02 / "questions.jsonl")]


def test_immutable_hash_is_stable_across_text_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_bytes(b'{"baseline": true}\n')
    lf_digest = _immutable_sha256(path)
    path.write_bytes(b'{"baseline": true}\r\n')

    assert _immutable_sha256(path) == lf_digest


def _must_reject(cases: list[dict[str, object]]) -> None:
    with pytest.raises(RagV02Error):
        audit_rag_v02(ROOT, cases=cases)


def test_rag_v02_has_exact_case_split_and_category_distribution() -> None:
    audit = audit_rag_v02(ROOT)

    assert audit.case_count == 120
    assert audit.normalized_v01_query_overlap_count == 0
    assert audit.split_counts == {"dev": 96, "release_holdout": 24}
    assert audit.category_split_counts == {
        "shipping": {"dev": 10, "release_holdout": 2, "total": 12},
        "returns": {"dev": 10, "release_holdout": 2, "total": 12},
        "refunds": {"dev": 8, "release_holdout": 2, "total": 10},
        "warranty": {"dev": 8, "release_holdout": 2, "total": 10},
        "payments": {"dev": 6, "release_holdout": 2, "total": 8},
        "privacy": {"dev": 5, "release_holdout": 1, "total": 6},
        "product-guides": {"dev": 13, "release_holdout": 3, "total": 16},
        "faq": {"dev": 12, "release_holdout": 4, "total": 16},
        "no-answer": {"dev": 24, "release_holdout": 6, "total": 30},
    }
    assert audit.dataset_version == "rag-v0.2"
    assert (
        audit.manifest_sha256 == "34206184a0c6c41657fb7dcf5ad61645e711420e28b00d06a9c3db04f4e3dc38"
    )


def test_rag_v02_rejects_duplicate_ids_and_normalized_queries() -> None:
    cases = _cases()
    cases[1]["case_id"] = cases[0]["case_id"]
    _must_reject(cases)

    cases = _cases()
    cases[1]["query"] = str(cases[0]["query"]).upper().replace("?", "!!!")
    _must_reject(cases)


def test_rag_v02_rejects_query_overlap_and_punctuation_rewrite_of_v01() -> None:
    cases = _cases()
    v01 = json.loads(
        (ROOT / "evals/rag/v0.1/questions.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    cases[0]["query"] = str(v01["query"]).upper().replace("?", "!!!")
    _must_reject(cases)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda case: case["relevance_judgments"][0].update(chunk_index=99),
        lambda case: case.update(relevance_judgments=[]),
        lambda case: case.update(answerable=False),
        lambda case: case["expected_facts"][0].update(statement="a made-up unsupported statement"),
    ],
    ids=[
        "bad-locator",
        "answerable-without-relevance",
        "no-answer-with-positive-relevance",
        "unsupported-fact",
    ],
)
def test_rag_v02_rejects_bad_evidence_and_answerability(mutate: object) -> None:
    cases = _cases()
    mutate(cases[0])  # type: ignore[operator]
    _must_reject(cases)


def test_rag_v02_rejects_duplicate_normalized_query_answer_pair() -> None:
    cases = _cases()
    cases[1]["query"] = cases[0]["query"]
    cases[1]["expected_answer"] = cases[0]["expected_answer"]
    _must_reject(cases)


def test_holdout_guard_defaults_to_dev_and_fails_closed(tmp_path: Path) -> None:
    assert guard_rag_v02_split() == "dev"
    with pytest.raises(RagV02Error, match="selection"):
        guard_rag_v02_split("release_holdout")
    malformed = tmp_path / "selection.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(RagV02Error, match="malformed"):
        guard_rag_v02_split("release_holdout", selection_path=malformed)

    missing_provenance = tmp_path / "missing-provenance.json"
    missing_provenance.write_text("{}", encoding="utf-8")
    with pytest.raises(RagV02Error, match="provenance"):
        guard_rag_v02_split("release_holdout", selection_path=missing_provenance)

    malformed.write_text(
        json.dumps(
            {
                "benchmark_version": "rag-v0.2",
                "dataset_sha256": "0" * 64,
                "knowledge_manifest_sha256": "0" * 64,
                "selected_gate": "G0_CURRENT_RRF",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RagV02Error, match="provenance"):
        guard_rag_v02_split("release_holdout", selection_path=malformed)


def test_experiment_plan_has_preregistered_candidate_ids_and_rules() -> None:
    plan = validate_experiment_plan(V02 / "experiment-plan.json")

    assert [item["id"] for item in plan["evidence_gates"]] == [
        "G0_CURRENT_RRF",
        "G1_DENSE_SIMILARITY",
        "G2_TOP_EVIDENCE_CROSS_ENCODER",
    ]
    assert [item["id"] for item in plan["grounding_candidates"]] == [
        "P0_CURRENT",
        "P1_PROMPT_V3",
        "P2_FAIL_CLOSED_CITATIONS",
        "P3_ONE_REPAIR_THEN_FAIL_CLOSED",
    ]
    assert [item["id"] for item in plan["model_candidates"]] == [
        "M0",
        "M1",
    ]
    assert plan["evidence_gate_selection"]["minimum_dev_no_answer_rejection"] == 0.9
    assert plan["evidence_gate_selection"]["p95_latency_tie_band"] == 0.02
    assert plan["evidence_gate_selection"]["ordered_rules"] == [
        "minimum_no_answer_rejection_90_percent",
        "maximize_answerable_acceptance",
        "within_2_percentage_points_prefer_lower_p95_latency",
        "then_prefer_fewer_inference_components_and_simpler_behavior",
        "never_use_release_holdout",
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda plan: plan["grounding_candidates"][2].update(definition="P1 only"),
        lambda plan: plan["model_candidates"][1].update(preferred_serving="hosted vendor endpoint"),
        lambda plan: plan["model_selection_guard"].update(stage4_release_holdout_for_tuning=True),
    ],
    ids=["grounding-definition", "model-serving", "stage4-holdout-guard"],
)
def test_experiment_plan_rejects_candidate_or_selection_guard_drift(
    mutate: object, tmp_path: Path
) -> None:
    plan = json.loads((V02 / "experiment-plan.json").read_text(encoding="utf-8"))
    mutate(plan)  # type: ignore[operator]
    path = tmp_path / "experiment-plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(RagV02Error):
        validate_experiment_plan(path)


def test_m5d_protects_locked_benchmark_baselines_profile_prompt_and_tools() -> None:
    expected = {
        "evals/rag/v0.1/questions.jsonl": "05ee4c5064db8eafa7a1660f38fb3cb518965229fac8346593a93da75c1991f3",
        "evals/rag/v0.1/manifest.json": "0fb09d592fc17a2194e11dbbde57b76e8a9ddd4dd9f7a364c5a92f4a3d2e899f",
        "evals/rag/v0.1/selection.json": "b91d1ce9ca161c0e2767a453bcd72f338ba9884bf1a244db58b4be5b1491470d",
        "evals/baselines/stage5-rag-v0.1-baseline.json": "55897b22bc0b740b5041e33cc3086f3a4adddcc28124890c35ef6087c5a4af48",
        "knowledge/novacommerce/manifest.json": "26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660",
        "evals/baselines/stage4-agent-v0.1-baseline.json": "847eb19848522de390cf2b0bbe089a317b97d0e0f462d62a9e958cba229b4088",
        "src/verbaops/retrieval/profile.py": "562d46b36e2f211bbc5f9865a370f75bac0b82b35f13eb54ea8e6d5fe8c3e630",
        "src/verbaops/agent/prompts/system_v2.txt": "023cccc5c91a9f1295928e4ee8503d5caf8cb100e243d8deb90762cd11476b74",
        "src/verbaops/agent/versions.py": "7fcc375a05a5a6523e2bd399ac0615e2d4f9b402665e873a4c2c4b58b1fa8156",
        "src/verbaops/tools/commerce_reads.py": "fe501302c4e34794af413f5b08284d6a850a6fdc7bdcd15c798892a25786d668",
        "src/verbaops/tools/models.py": "5a2fd1d22bd407afc06ab8304b9f56d7536e83810fd8ecc722464dc80f126e66",
        "src/verbaops/tools/registry.py": "84a2dd4b0f624276bf3dc87455a3740bced148c5822117797458d5b9ac422544",
    }

    observed = {path: _immutable_sha256(ROOT / path) for path in expected}

    assert observed == expected
