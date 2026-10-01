"""Provider-free M5D-A corpus, guard, plan, and immutability contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from verbaops.evaluation.rag_grounding import score_grounded_records
from verbaops.evaluation.rag_metrics import grounded_fact_score
from verbaops.evaluation.rag_v02 import (
    RagV02Error,
    audit_rag_v02,
    guard_rag_v02_split,
    load_rag_v02_cases,
    recognize_labeled_fact_assertion,
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


def _future_selection_artifact() -> dict[str, object]:
    dataset_sha = hashlib.sha256((V02 / "questions.jsonl").read_bytes()).hexdigest()
    knowledge_sha = hashlib.sha256(
        (ROOT / "knowledge/novacommerce/manifest.json").read_bytes()
    ).hexdigest()
    plan_sha = hashlib.sha256((V02 / "experiment-plan.json").read_bytes()).hexdigest()
    return {
        "benchmark_version": "rag-v0.2",
        "dataset_sha256": dataset_sha,
        "knowledge_manifest_sha256": knowledge_sha,
        "experiment_plan_sha256": plan_sha,
        "selected_gate": "G0_CURRENT_RRF",
        "selected_gate_threshold": 0.02,
        "selected_grounding_candidate": "P0_CURRENT",
        "selected_model_candidate": "M0",
        "retrieval_profile_version": "knowledge-retrieval-v1.1",
        "agent_prompt_version": "text-agent-system-v2",
        "agent_graph_version": "text-agent-v2",
        "selection_git_sha": "d" * 40,
        "selected_at_utc": "2026-09-29T12:00:00Z",
        "selected_before_holdout": True,
        "dev_evidence": {
            "benchmark_version": "rag-v0.2",
            "split": "dev",
            "case_count": 96,
            "dataset_sha256": dataset_sha,
            "knowledge_manifest_sha256": knowledge_sha,
            "experiment_plan_sha256": plan_sha,
            "run_id": "m5d-dev-run-example",
            "artifact_path": "artifacts/m5d/dev-summary.json",
            "artifact_sha256": "e" * 64,
            "evaluated_git_sha": "c" * 40,
            "completed_at_utc": "2026-09-29T11:00:00Z",
            "selected_candidate": {
                "gate": "G0_CURRENT_RRF",
                "threshold": 0.02,
                "grounding": "P0_CURRENT",
                "model": "M0",
            },
            "metrics": {
                "answerable_acceptance": 0.70,
                "no_answer_rejection": 0.90,
                "citation_precision": 0.71,
                "labeled_groundedness": 0.15,
                "unsupported_recognized_fact_rate": 0.85,
                "expected_fact_coverage": 0.39,
                "answer_p95_latency_ms": 100.0,
            },
        },
    }


def _write_selection(path: Path, artifact: dict[str, object]) -> None:
    path.write_text(json.dumps(artifact, allow_nan=True), encoding="utf-8")


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
        audit.manifest_sha256 == "f5badb26ee596d795e74ab4d709a99a83b3eec1f2a12eb7c29a9667c7d4c02a9"
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


def test_holdout_guard_accepts_only_complete_future_selection_provenance(
    tmp_path: Path,
) -> None:
    selection_path = tmp_path / "selection.json"
    _write_selection(selection_path, _future_selection_artifact())

    assert (
        guard_rag_v02_split("release_holdout", selection_path=selection_path) == "release_holdout"
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda selection: selection.pop("benchmark_version"),
        lambda selection: selection.pop("dataset_sha256"),
        lambda selection: selection.pop("knowledge_manifest_sha256"),
        lambda selection: selection.pop("experiment_plan_sha256"),
        lambda selection: selection.pop("selected_gate"),
        lambda selection: selection.pop("selected_gate_threshold"),
        lambda selection: selection.update(selected_gate="G9_UNKNOWN"),
        lambda selection: selection.update(selected_grounding_candidate="P9_UNKNOWN"),
        lambda selection: selection.update(selected_model_candidate="M9_UNKNOWN"),
        lambda selection: selection.update(selected_gate_threshold=float("nan")),
        lambda selection: selection.update(dataset_sha256="0" * 64),
        lambda selection: selection.update(knowledge_manifest_sha256="0" * 64),
        lambda selection: selection.update(experiment_plan_sha256="0" * 64),
        lambda selection: selection.pop("selected_grounding_candidate"),
        lambda selection: selection.pop("selected_model_candidate"),
        lambda selection: selection.pop("retrieval_profile_version"),
        lambda selection: selection.pop("agent_prompt_version"),
        lambda selection: selection.pop("agent_graph_version"),
        lambda selection: selection.pop("selection_git_sha"),
        lambda selection: selection.pop("selected_at_utc"),
        lambda selection: selection.pop("selected_before_holdout"),
        lambda selection: selection.pop("dev_evidence"),
        lambda selection: selection.update(selected_before_holdout=False),
    ],
    ids=[
        "missing-benchmark-version",
        "missing-dataset-sha",
        "missing-knowledge-sha",
        "missing-experiment-plan-sha",
        "missing-gate",
        "missing-threshold",
        "unknown-gate",
        "unknown-grounding",
        "unknown-model",
        "non-finite-threshold",
        "dataset-sha-mismatch",
        "knowledge-sha-mismatch",
        "experiment-plan-sha-mismatch",
        "missing-grounding",
        "missing-model",
        "missing-retrieval-version",
        "missing-prompt-version",
        "missing-graph-version",
        "missing-selection-commit",
        "missing-selection-time",
        "missing-before-holdout-provenance",
        "missing-dev-evidence",
        "selection-not-before-holdout",
    ],
)
def test_holdout_guard_rejects_invalid_future_selection_provenance(
    mutate: object, tmp_path: Path
) -> None:
    artifact = _future_selection_artifact()
    mutate(artifact)  # type: ignore[operator]
    selection_path = tmp_path / "selection.json"
    _write_selection(selection_path, artifact)

    with pytest.raises(RagV02Error):
        guard_rag_v02_split("release_holdout", selection_path=selection_path)


def test_holdout_guard_rejects_incomplete_or_ineligible_dev_evidence(tmp_path: Path) -> None:
    artifact = _future_selection_artifact()
    evidence = artifact["dev_evidence"]
    assert isinstance(evidence, dict)
    evidence["selected_candidate"]["model"] = "M1"
    path = tmp_path / "candidate-mismatch.json"
    _write_selection(path, artifact)
    with pytest.raises(RagV02Error):
        guard_rag_v02_split("release_holdout", selection_path=path)

    artifact = _future_selection_artifact()
    evidence = artifact["dev_evidence"]
    assert isinstance(evidence, dict)
    evidence["knowledge_manifest_sha256"] = "0" * 64
    path = tmp_path / "knowledge-hash-mismatch.json"
    _write_selection(path, artifact)
    with pytest.raises(RagV02Error):
        guard_rag_v02_split("release_holdout", selection_path=path)

    artifact = _future_selection_artifact()
    artifact["selected_at_utc"] = "2026-09-29T10:00:00Z"
    path = tmp_path / "selection-before-dev.json"
    _write_selection(path, artifact)
    with pytest.raises(RagV02Error):
        guard_rag_v02_split("release_holdout", selection_path=path)

    artifact = _future_selection_artifact()
    evidence = artifact["dev_evidence"]
    assert isinstance(evidence, dict)
    evidence["metrics"]["no_answer_rejection"] = 0.89
    path = tmp_path / "ineligible-gate.json"
    _write_selection(path, artifact)
    with pytest.raises(RagV02Error):
        guard_rag_v02_split("release_holdout", selection_path=path)


def test_rag_v02_assertion_recognition_does_not_count_safe_refusals() -> None:
    alias = "the return window is 30 days"

    assert recognize_labeled_fact_assertion("The return window is 30 days.", [alias])
    assert not recognize_labeled_fact_assertion(
        "I cannot verify whether the return window is 30 days.", [alias]
    )
    assert not recognize_labeled_fact_assertion(
        "The available evidence does not confirm a 30-day return window.",
        ["a 30 day return window"],
    )
    assert not recognize_labeled_fact_assertion(
        "I don't have enough company information to say that the return window is 30 days.",
        [alias],
    )


def test_assertion_recognition_change_is_opt_in_for_v02_only() -> None:
    answer = "I cannot verify whether the return window is 30 days."
    fact: dict[str, object] = {
        "fact_id": "return-window",
        "aliases": ["the return window is 30 days"],
    }

    # The default scorer keeps the frozen v0.1 matching behavior.
    assert grounded_fact_score(answer, [fact], []).recognized == 1
    assert (
        grounded_fact_score(
            answer,
            [fact],
            [],
            assertion_recognizer=recognize_labeled_fact_assertion,
        ).recognized
        == 0
    )


def test_rag_v02_assertion_recognition_accepts_benchmark_alias_paraphrase() -> None:
    first_case = load_rag_v02_cases(V02 / "questions.jsonl")[0]
    fact = first_case.expected_facts[0]
    paraphrase = "Standard parcels usually arrive three to five business days after dispatch."

    assert paraphrase in fact.aliases
    assert recognize_labeled_fact_assertion(paraphrase, fact.aliases)


def test_rag_v02_grounding_scorer_uses_assertion_recognition() -> None:
    case = load_rag_v02_cases(V02 / "questions.jsonl")[0]
    refusal = score_grounded_records(
        [case],
        [
            {
                "case_id": case.case_id,
                "final_answer": "I cannot verify whether standard delivery normally arrives in three to five business days after dispatch.",
                "public_citations": [],
                "top_confidence_score": 0.1,
            }
        ],
        threshold=0.032018442622950824,
    )
    assert refusal["groundedness"] == {"numerator": 0, "denominator": 0, "value": None}
    assert refusal["expected_fact_coverage"] == {"numerator": 0, "denominator": 1, "value": 0.0}

    assertion = score_grounded_records(
        [case],
        [
            {
                "case_id": case.case_id,
                "final_answer": "Standard parcels usually arrive three to five business days after dispatch.",
                "public_citations": [],
                "top_confidence_score": 0.1,
            }
        ],
        threshold=0.032018442622950824,
    )
    assert assertion["groundedness"] == {"numerator": 0, "denominator": 1, "value": 0.0}
    assert assertion["expected_fact_coverage"] == {"numerator": 1, "denominator": 1, "value": 1.0}


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
    assert plan["evidence_gate_selection"]["answerable_acceptance_tie_band"] == 0.02
    assert "p95_latency_tie_band" not in plan["evidence_gate_selection"]
    assert plan["evidence_gate_selection"]["tie_band_unit"] == "percentage_points"
    assert plan["evidence_gate_selection"]["ordered_rules"] == [
        "minimum_no_answer_rejection_90_percent",
        "maximize_answerable_acceptance",
        "within_2_percentage_points_prefer_lower_p95_latency",
        "then_prefer_fewer_inference_components_and_simpler_behavior",
        "never_use_release_holdout",
    ]

    confidence = plan["evidence_gate_confidence"]
    assert confidence["ranking_and_candidates"] == (
        "Keep the frozen hybrid_rrf ranking and the exact same final top-five evidence candidates for G0, G1, and G2."
    )
    assert confidence["one_query_one_scalar"] is True
    assert confidence["threshold_acceptance"] == "score >= threshold"
    assert confidence["threshold_rejection"] == "score < threshold"
    assert confidence["thresholds_candidate_specific"] is True
    assert confidence["compare_raw_scores_across_candidates"] is False
    assert confidence["query_confidence_by_candidate"] == {
        "G0_CURRENT_RRF": "Frozen top hybrid-RRF score for the query from knowledge-retrieval-v1.1.",
        "G1_DENSE_SIMILARITY": "Maximum E5 cosine similarity between the existing query embedding and stored document embeddings for exactly the same final five hybrid evidence candidates, including candidates that entered through lexical retrieval and had no dense rank.",
        "G2_TOP_EVIDENCE_CROSS_ENCODER": "Maximum relevance score from cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 revision 1427fd652930e4ba29e8149678df786c240d8825 over exactly the same final five hybrid evidence candidates.",
    }


def test_m5d_b_plan_freezes_candidate_threshold_selection_and_quality_gates() -> None:
    plan = validate_experiment_plan(V02 / "experiment-plan.json")

    assert plan["schema_version"] == "m5d-experiment-plan-v1.1"
    gate_selection = plan["evidence_gate_selection"]
    assert gate_selection["within_gate_threshold_order"] == [
        "require_at_least_90_percent_dev_no_answer_rejection",
        "maximize_answerable_acceptance",
        "maximize_no_answer_rejection",
        "prefer_higher_threshold",
    ]
    assert gate_selection["minimum_dev_no_answer_rejection"] == 0.9
    assert gate_selection["minimum_dev_no_answer_rejected_cases"] == 22
    assert gate_selection["answerable_acceptance_target"] == 0.7
    assert gate_selection["answerable_acceptance_tie_band"] == 0.02
    assert gate_selection["tie_band_unit"] == "percentage_points"
    assert gate_selection["across_gate_order"] == [
        "eligible_no_answer_rejection_90_percent",
        "maximize_answerable_acceptance",
        "within_2_percentage_points_prefer_lower_total_p95_latency",
        "then_prefer_fewer_inference_components",
        "candidate_id_ascending",
    ]
    assert gate_selection["gate_candidate_complexity"] == {
        "G0_CURRENT_RRF": 1,
        "G1_DENSE_SIMILARITY": 2,
        "G2_TOP_EVIDENCE_CROSS_ENCODER": 3,
    }
    assert gate_selection["latency_components_by_gate"] == {
        "G0_CURRENT_RRF": ["hybrid_retrieval"],
        "G1_DENSE_SIMILARITY": [
            "hybrid_retrieval",
            "e5_candidate_vector_fetch",
            "e5_cosine_scoring",
        ],
        "G2_TOP_EVIDENCE_CROSS_ENCODER": [
            "hybrid_retrieval",
            "cross_encoder_scoring",
        ],
    }
    assert plan["grounding_quality_gates"] == {
        "citation_precision_minimum": 0.95,
        "citation_precision_requires_nonzero_denominator": True,
        "labeled_groundedness_minimum": 0.9,
        "unsupported_recognized_fact_rate_maximum": 0.1,
        "expected_fact_coverage_minimum": 0.7,
        "no_qualifying_candidate_outcome": "NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE",
    }
    assert plan["grounding_selection_tie_breaks"] == [
        "citation_precision_within_1_percentage_point",
        "labeled_groundedness_within_1_percentage_point",
        "minimize_unsupported_units_within_1_percentage_point",
        "expected_fact_coverage_within_2_percentage_points",
        "lower_answer_p95_latency",
        "lower_mean_cost_among_cost_covered_observations",
        "fewer_inference_components_P0_1_to_P3_4",
        "candidate_id_ascending",
    ]
    assert plan["grounding_remediation_target"] == {
        "answerable_acceptance_minimum": 0.7,
        "mandatory_no_answer_rejection_minimum": 0.9,
    }


def test_m5d_b_plan_freezes_stage4_guard_and_m0_first_execution() -> None:
    plan = validate_experiment_plan(V02 / "experiment-plan.json")

    assert plan["model_execution_policy"] == {
        "candidate_order": ["M0", "M1"],
        "m0_must_run_first": True,
        "m1_requires_separately_configured_local_openai_compatible_endpoint": True,
        "m1_unavailable_outcome": "M1_NOT_EXECUTED_LOCAL_RESOURCE_BLOCK",
        "retain_m0_without_comparison_outcome": "INCUMBENT_RETAINED_NO_EXECUTABLE_CHALLENGER",
        "no_model_substitution": True,
    }
    assert plan["stage4_dev_regression_guard"] == {
        "split": "dev",
        "case_count": 96,
        "control": "same_environment_M0_P0",
        "stage4_release_holdout_for_tuning": False,
        "maximum_s4_violations": 0,
        "maximum_unauthorized_actions": 0,
        "maximum_absolute_regression": 0.02,
        "maximum_unnecessary_tool_rate_increase": 0.02,
        "compared_metrics": [
            "tool_selection_quality",
            "valid_tool_arguments",
            "all_fields_correct",
            "task_completion",
            "unnecessary_tool_rate",
        ],
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda plan: plan.update(schema_version="m5d-experiment-plan-v1"),
        lambda plan: plan["evidence_gate_selection"].update(
            minimum_dev_no_answer_rejected_cases=21
        ),
        lambda plan: plan["evidence_gate_selection"].update(latency_components_by_gate={}),
        lambda plan: plan["grounding_quality_gates"].update(citation_precision_minimum=0.94),
        lambda plan: plan["grounding_selection_tie_breaks"].reverse(),
        lambda plan: plan["model_execution_policy"].update(candidate_order=["M1", "M0"]),
        lambda plan: plan["stage4_dev_regression_guard"].update(maximum_unauthorized_actions=1),
    ],
    ids=[
        "schema-version",
        "negative-eligibility-count",
        "gate-latency-components",
        "citation-quality-floor",
        "grounding-selection-order",
        "model-execution-order",
        "stage4-security-guard",
    ],
)
def test_m5d_b_plan_rejects_post_registration_rule_drift(mutate: object, tmp_path: Path) -> None:
    plan = json.loads((V02 / "experiment-plan.json").read_text(encoding="utf-8"))
    mutate(plan)  # type: ignore[operator]
    path = tmp_path / "experiment-plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(RagV02Error):
        validate_experiment_plan(path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda plan: plan["grounding_candidates"][2].update(definition="P1 only"),
        lambda plan: plan["model_candidates"][1].update(preferred_serving="hosted vendor endpoint"),
        lambda plan: plan["model_selection_guard"].update(stage4_release_holdout_for_tuning=True),
        lambda plan: plan["future_selection_artifact_contract"]["required_fields"].remove(
            "selected_model_candidate"
        ),
        lambda plan: plan["future_selection_artifact_contract"]["field_constraints"].update(
            selected_gate_threshold="any numeric value"
        ),
        lambda plan: plan["future_selection_artifact_contract"]["dev_evidence_contract"].update(
            dev_evidence_hashes_must_match_selection=False
        ),
    ],
    ids=[
        "grounding-definition",
        "model-serving",
        "stage4-holdout-guard",
        "selection-schema-required-fields",
        "selection-threshold-rule",
        "selection-dev-evidence-contract",
    ],
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda plan: plan["evidence_gate_confidence"]["query_confidence_by_candidate"].update(
            G1_DENSE_SIMILARITY="Maximum over unrelated dense top-20 candidates."
        ),
        lambda plan: plan["evidence_gate_confidence"].update(
            compare_raw_scores_across_candidates=True
        ),
        lambda plan: plan["evidence_gate_confidence"].update(
            ranking_and_candidates="Candidates can be reranked."
        ),
        lambda plan: plan["evidence_gate_confidence"].update(
            threshold_acceptance="score > threshold"
        ),
        lambda plan: plan["evidence_gate_confidence"]["query_confidence_by_candidate"].update(
            G2_TOP_EVIDENCE_CROSS_ENCODER="Maximum score over top-20 candidates."
        ),
    ],
    ids=[
        "g1-candidate-scope",
        "cross-candidate-scale",
        "frozen-ranking",
        "acceptance-boundary",
        "g2-candidate-scope",
    ],
)
def test_experiment_plan_rejects_query_confidence_semantics_drift(
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
