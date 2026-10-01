from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCORER_MODULE = "verbaops.evaluation.rag_v02_scorer_v2"
FREEZE_MODULE = "verbaops.evaluation.m5d_b2_preregistration"


def _module(name: str) -> Any:
    assert importlib.util.find_spec(name) is not None, f"required contract module missing: {name}"
    return importlib.import_module(name)


def test_scorer_v2_fixture_examples_cover_assertion_semantics() -> None:
    scorer = _module(SCORER_MODULE)
    audited = scorer.audit_scorer_v2(ROOT)
    assert audited["manifest"]["scorer_version"] == "rag-v0.2-scorer-v2"
    example_statuses = {
        example["expected_status"]
        for fact in audited["fixtures"]["representative_facts"]
        for example in fact["examples"]
    }
    assert {
        "asserted",
        "partial",
        "negated",
        "contradicted",
        "refusal",
        "quoted",
        "uncertain",
        "unrelated_overlap",
    } <= example_statuses

    for fact in audited["fixtures"]["representative_facts"]:
        for example in fact["examples"]:
            result = scorer.classify_labeled_fact_assertion(
                example["text"],
                fact["benchmark_aliases"],
                positive_paraphrases=fact["positive_paraphrases"],
                partial_patterns=fact["partial_patterns"],
                contradiction_patterns=fact["contradiction_patterns"],
            )
            assert result.status.value == example["expected_status"], example["id"]
            assert result.recognized is example["expected_recognized"], example["id"]


def test_scorer_v2_manifest_binds_only_dev_facts_and_fixture_bytes() -> None:
    scorer = _module(SCORER_MODULE)
    audited = scorer.audit_scorer_v2(ROOT)
    manifest = audited["manifest"]
    fixtures_path = ROOT / "evals/rag/v0.2/scorer-v2/fixtures.json"
    spec_path = ROOT / "evals/rag/v0.2/scorer-v2/spec.json"
    dataset_path = ROOT / "evals/rag/v0.2/questions.jsonl"

    assert manifest["fixture_data_sha256"] == hashlib.sha256(fixtures_path.read_bytes()).hexdigest()
    assert manifest["scorer_spec_sha256"] == hashlib.sha256(spec_path.read_bytes()).hexdigest()
    assert manifest["dataset_sha256"] == hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    assert manifest["fixture_provenance"]["p4_outputs_available_during_construction"] is False
    assert manifest["fixture_provenance"]["candidate_outputs_consulted"] == []
    assert len(manifest["source_fact_ids"]) == 72
    assert len(set(manifest["source_fact_ids"])) == 72
    assert manifest["scorer_frozen_at_commit_sha"] == "PENDING_LOCAL_FREEZE" or re.fullmatch(
        r"[a-f0-9]{40}", manifest["scorer_frozen_at_commit_sha"]
    )


def test_p4_preregistration_contract_is_dev_only_and_has_no_result_artifact() -> None:
    freeze = _module(FREEZE_MODULE)
    audit = freeze.audit_m5d_b2_preregistration(ROOT)
    plan = json.loads(
        (ROOT / "evals/rag/v0.2/m5d-b2-experiment-plan.json").read_text(encoding="utf-8")
    )

    assert audit["candidate_id"] == "P4_EVIDENCE_LINKED_SINGLE_PASS"
    assert audit["split"] == "dev"
    assert audit["case_count"] == 96
    assert audit["canonical_p4_results_present"] is False
    assert audit["release_holdout_accessed"] is False
    assert audit["selection_json_present"] is False
    assert plan["frozen_environment"]["evidence_gate"] == "G2_TOP_EVIDENCE_CROSS_ENCODER"
    assert plan["frozen_environment"]["evidence_gate_threshold"] == 0.2554669
    assert plan["frozen_environment"]["model"] == "groq/openai/gpt-oss-120b"
    assert plan["candidate"]["structured_final_answer_generations_per_case_answer"] == 1
    assert plan["candidate"]["candidate_specific_repair_generations"] == 0
    assert plan["candidate"]["agent_prompt_version"] == "text-agent-system-p4-evidence-linked-v1"
    assert plan["candidate"]["grounding_finalizer_version"] == "evidence-linked-single-pass-v1"
    assert plan["candidate"]["validation"]["handle_must_belong_to_supplied_selected_evidence"]
    assert plan["candidate"]["validation"]["supporting_excerpt_must_be_an_exact_source_substring"]
    assert "not semantic entailment" in plan["candidate"]["explicit_limitation"]
    assert plan["provider_call_budget"]["public_case_requests"] == 96
    assert plan["provider_call_budget"]["maximum_model_calls_total"] == 384
    assert plan["quality_floors"] == {
        "citation_precision_minimum": 0.95,
        "citation_precision_requires_nonzero_denominator": True,
        "labeled_groundedness_minimum": 0.9,
        "labeled_groundedness_requires_nonzero_denominator": True,
        "unsupported_recognized_fact_rate_maximum": 0.1,
        "expected_fact_coverage_minimum": 0.7,
        "zero_fabricated_or_non_supplied_evidence_handles": True,
        "trust_invariant_replaces_no_quality_floor": True,
    }
    assert "application_under_test_sha" in plan["run_identity"]["required_fields"]
    assert "evaluation_harness_sha" in plan["run_identity"]["required_fields"]
    assert "grounding_finalizer_version" in plan["run_identity"]["required_fields"]
    assert plan["resume_identity"]["incompatible_identity_fails_closed"] is True
    assert plan["resume_identity"]["completed_cases_are_never_replayed"] is True


def test_future_p4_inference_requires_green_ci_on_exact_freeze_commit() -> None:
    freeze = _module(FREEZE_MODULE)
    commit_sha = "a" * 40
    jobs = dict.fromkeys(freeze.REQUIRED_HOSTED_CI_JOBS, "success")

    with pytest.raises(ValueError, match="hosted CI run ID"):
        freeze.require_p4_inference_authorized(
            freeze_commit_sha=commit_sha,
            hosted_ci_run_id=None,
            hosted_ci_head_sha=commit_sha,
            hosted_ci_conclusion="success",
            job_conclusions=jobs,
        )
    with pytest.raises(ValueError, match="freeze commit"):
        freeze.require_p4_inference_authorized(
            freeze_commit_sha=None,
            hosted_ci_run_id=123,
            hosted_ci_head_sha=commit_sha,
            hosted_ci_conclusion="success",
            job_conclusions=jobs,
        )
    with pytest.raises(ValueError, match="exact freeze commit"):
        freeze.require_p4_inference_authorized(
            freeze_commit_sha=commit_sha,
            hosted_ci_run_id=123,
            hosted_ci_head_sha="b" * 40,
            hosted_ci_conclusion="success",
            job_conclusions=jobs,
        )
    with pytest.raises(ValueError, match="successful hosted CI"):
        freeze.require_p4_inference_authorized(
            freeze_commit_sha=commit_sha,
            hosted_ci_run_id=123,
            hosted_ci_head_sha=commit_sha,
            hosted_ci_conclusion="failure",
            job_conclusions=jobs,
        )
    with pytest.raises(ValueError, match="required jobs"):
        freeze.require_p4_inference_authorized(
            freeze_commit_sha=commit_sha,
            hosted_ci_run_id=123,
            hosted_ci_head_sha=commit_sha,
            hosted_ci_conclusion="success",
            job_conclusions={"quality": "success"},
        )

    freeze.require_p4_inference_authorized(
        freeze_commit_sha=commit_sha,
        hosted_ci_run_id=123,
        hosted_ci_head_sha=commit_sha,
        hosted_ci_conclusion="success",
        job_conclusions=jobs,
    )


def test_p4_schema_is_claim_linked_and_forbids_global_citations() -> None:
    schema = json.loads(
        (ROOT / "evals/rag/v0.2/scorer-v2/p4-output.schema.json").read_text(encoding="utf-8")
    )

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["claims"]
    claim = schema["$defs"]["claim"]
    assert claim["required"] == ["claim_text", "evidence_handle", "supporting_excerpt"]
    assert claim["additionalProperties"] is False
    assert "citations" not in schema["properties"]
