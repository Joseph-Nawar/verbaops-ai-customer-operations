from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCORER_MODULE = "verbaops.evaluation.rag_v02_scorer_impl"
AUDIT_MODULE = "verbaops.evaluation.rag_v02_scorer_v2"
FREEZE_MODULE = "verbaops.evaluation.m5d_b2_preregistration"


def _module(name: str) -> Any:
    assert importlib.util.find_spec(name) is not None, f"required contract module missing: {name}"
    return importlib.import_module(name)


def _audit() -> Any:
    return _module(AUDIT_MODULE)


def _assessment(
    scorer: Any,
    fact: dict[str, Any],
    text: str,
    *,
    partial_patterns: list[str] | None = None,
    contradiction_patterns: list[str] | None = None,
) -> Any:
    return scorer.classify_labeled_fact_assertion(
        text,
        fact["benchmark_aliases"],
        positive_paraphrases=fact["positive_paraphrases"],
        partial_patterns=partial_patterns or [],
        contradiction_patterns=contradiction_patterns or [],
    )


def _copy_audit_repo(destination: Path) -> Path:
    """Copy only provider-free scorer audit inputs; candidate outputs are excluded."""
    manifest = json.loads(
        (ROOT / "evals/rag/v0.2/scorer-v2/manifest.json").read_text(encoding="utf-8")
    )
    paths = {
        "evals/rag/v0.2/questions.jsonl",
        "evals/rag/v0.2/m5d-b2-experiment-plan.json",
        "evals/rag/v0.2/scorer-v2/manifest.json",
        "evals/rag/v0.2/scorer-v2/fixtures.json",
        "evals/rag/v0.2/scorer-v2/spec.json",
        "evals/rag/v0.2/scorer-v2/p4-output.schema.json",
        manifest["scorer_implementation_path"],
        "knowledge/novacommerce/manifest.json",
        *manifest["source_corpus_sha256"],
    }
    for relative in paths:
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return destination


def test_all_72_dev_fact_fixtures_and_authored_paraphrases_are_recognized() -> None:
    scorer = _module(SCORER_MODULE)
    audited = _audit().audit_scorer_v2(ROOT)
    manifest = audited["manifest"]
    facts = audited["fixtures"]["facts"]
    fact_keys = [f"{fact['case_id']}::{fact['fact_id']}" for fact in facts]

    assert len(facts) == 72
    assert manifest["fixture_fact_count"] == 72
    assert manifest["authored_positive_paraphrase_count"] == 72
    assert len(set(fact_keys)) == 72
    assert set(fact_keys) == set(manifest["source_fact_ids"])
    assert set(fact_keys) == audited["fixture_fact_keys"]
    for fact in facts:
        assert fact["positive_paraphrases"]
        assert all(paraphrase.strip() for paraphrase in fact["positive_paraphrases"])
        for alias in fact["benchmark_aliases"]:
            result = scorer.classify_labeled_fact_assertion(alias, fact["benchmark_aliases"])
            assert result.status.value == "asserted", fact["case_id"]
            assert result.recognized is True, fact["case_id"]
        for paraphrase in fact["positive_paraphrases"]:
            result = _assessment(scorer, fact, paraphrase)
            assert result.status.value == "asserted", fact["case_id"]
            assert result.recognized is True, fact["case_id"]


def test_compact_negative_regressions_preserve_assertion_semantics() -> None:
    scorer = _module(SCORER_MODULE)
    audited = _audit().audit_scorer_v2(ROOT)
    fixtures = audited["fixtures"]
    fact_by_key = {f"{fact['case_id']}::{fact['fact_id']}": fact for fact in fixtures["facts"]}
    matrix = fixtures["semantic_regression_matrix"]
    expected_statuses = {
        "partial",
        "negated",
        "contradicted",
        "refusal",
        "quoted",
        "uncertain",
        "unrelated_overlap",
        "asserted",
    }
    observed_statuses: set[str] = set()
    expected_examples = {
        "returns-complete-assertion": ("asserted", True),
        "returns-valid-authored-paraphrase": ("asserted", True),
        "returns-contradictory-time-window": ("contradicted", False),
        "returns-uncertain-30-day-mention": ("uncertain", False),
        "returns-partial-compound": ("partial", False),
        "returns-negated-complete-fact": ("negated", False),
        "returns-refusal-repeats-fact": ("refusal", False),
        "returns-quoted-fact": ("quoted", False),
        "returns-uncertain-fact": ("uncertain", False),
        "returns-unrelated-overlap": ("unrelated_overlap", False),
        "pending-authorization-negative-form-is-asserted": ("asserted", True),
        "pending-authorization-valid-paraphrase-is-asserted": ("asserted", True),
        "charger-negative-wording-is-asserted": ("asserted", True),
        "charger-valid-negative-form-paraphrase-is-asserted": ("asserted", True),
        "charger-contradictory-claim": ("contradicted", False),
    }
    seen_examples: dict[str, tuple[str, bool]] = {}

    for regression in matrix:
        key = f"{regression['case_id']}::{regression['fact_id']}"
        fact = fact_by_key[key]
        for example in regression["examples"]:
            result = _assessment(
                scorer,
                fact,
                example["text"],
                partial_patterns=regression.get("partial_patterns"),
                contradiction_patterns=regression.get("contradiction_patterns"),
            )
            assert result.status.value == example["expected_status"], example["id"]
            assert result.recognized is example["expected_recognized"], example["id"]
            observed_statuses.add(result.status.value)
            seen_examples[example["id"]] = (result.status.value, result.recognized)

    assert seen_examples == expected_examples
    assert expected_statuses <= observed_statuses
    feature_tags = {tag for regression in matrix for tag in regression.get("feature_tags", [])}
    assert {
        "affirmative_fact",
        "compound",
        "conditional_eligibility",
        "numeric_time_window",
        "inherently_negative_fact",
    } <= feature_tags
    assert fixtures["negative_matrix_provenance"]["candidate_outputs_consulted"] == []
    assert fixtures["negative_matrix_provenance"]["p2_p3_answer_text_used"] is False
    assert fixtures["negative_matrix_provenance"]["p4_outputs_available"] is False


def test_scorer_manifest_binds_full_dev_fixture_and_immutable_inputs() -> None:
    audited = _audit().audit_scorer_v2(ROOT)
    manifest = audited["manifest"]
    fixtures_path = ROOT / "evals/rag/v0.2/scorer-v2/fixtures.json"
    spec_path = ROOT / "evals/rag/v0.2/scorer-v2/spec.json"
    dataset_path = ROOT / "evals/rag/v0.2/questions.jsonl"
    implementation_path = ROOT / manifest["scorer_implementation_path"]

    assert manifest["fixture_data_sha256"] == hashlib.sha256(fixtures_path.read_bytes()).hexdigest()
    assert manifest["scorer_spec_sha256"] == hashlib.sha256(spec_path.read_bytes()).hexdigest()
    assert manifest["fixture_data_sha256"] == (
        "7dd8662d39b14c71c01fad309341c478401d649f7165ae4ced384053b420675a"
    )
    assert manifest["scorer_spec_sha256"] == (
        "55eb54f61be1dfe6536a23f0786021b193e032dfa0fdc760bc2caa6c5688f120"
    )
    assert manifest["dataset_sha256"] == hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    assert manifest["fixture_provenance"]["p4_outputs_available_during_construction"] is False
    assert manifest["fixture_provenance"]["candidate_outputs_consulted"] == []
    assert manifest["fixture_provenance"]["p2_p3_answer_text_used"] is False
    assert len(manifest["source_fact_ids"]) == 72
    assert len(set(manifest["source_fact_ids"])) == 72
    assert re.fullmatch(r"[a-f0-9]{40}", manifest["scorer_frozen_at_commit_sha"])
    assert (
        manifest["scorer_implementation_sha256"]
        == hashlib.sha256(implementation_path.read_bytes()).hexdigest()
    )
    assert manifest["scorer_implementation_sha256"] == (
        "aa0eff0b165a8d40e22416bad493f432931409ca70d2abee89682966c39df67a"
    )
    assert manifest["scorer_entrypoint"] == (
        "verbaops.evaluation.rag_v02_scorer_impl.classify_labeled_fact_assertion"
    )
    assert manifest["scorer_frozen_at_commit_sha"] == "fa800f5bfee4ee903905d89bf600642e9ddb0d95"
    assert manifest["scorer_frozen_at_commit_sha"] != ("c8a55e63c20e209d7ee920c3020977d001b41a1b")


def test_only_hash_bound_module_exports_the_scorer_entrypoint() -> None:
    scorer = _module(SCORER_MODULE)
    audit = _audit()
    assert scorer.__file__ is not None
    assert (
        Path(scorer.__file__).resolve()
        == (ROOT / "src/verbaops/evaluation/rag_v02_scorer_impl.py").resolve()
    )
    assert callable(scorer.classify_labeled_fact_assertion)
    assert not hasattr(audit, "classify_labeled_fact_assertion")


@pytest.mark.parametrize(
    ("relative_path", "manifest_field"),
    [
        ("evals/rag/v0.2/scorer-v2/fixtures.json", "fixture_data_sha256"),
        ("evals/rag/v0.2/scorer-v2/spec.json", "scorer_spec_sha256"),
        (None, "scorer_implementation_sha256"),
    ],
)
def test_tampered_frozen_scorer_artifact_hash_is_rejected(
    tmp_path: Path, relative_path: str | None, manifest_field: str
) -> None:
    scorer = _audit()
    manifest = _audit().audit_scorer_v2(ROOT)["manifest"]
    original_path = ROOT / (relative_path or manifest["scorer_implementation_path"])
    copied_root = _copy_audit_repo(tmp_path / "repo")
    tampered = copied_root / (relative_path or manifest["scorer_implementation_path"])
    suffix = b" \n" if relative_path else b"\n# contract drift\n"
    tampered.write_bytes(original_path.read_bytes() + suffix)

    with pytest.raises(scorer.ScorerV2Error, match="SHA256 mismatch"):
        scorer.audit_scorer_v2(copied_root)


def test_incompatible_manifest_binding_is_rejected(tmp_path: Path) -> None:
    scorer = _audit()
    copied_root = _copy_audit_repo(tmp_path / "repo")
    manifest_path = copied_root / "evals/rag/v0.2/scorer-v2/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scorer_implementation_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(scorer.ScorerV2Error, match="scorer implementation SHA256 mismatch"):
        scorer.audit_scorer_v2(copied_root)


def test_incompatible_plan_binding_is_rejected(tmp_path: Path) -> None:
    freeze = _module(FREEZE_MODULE)
    copied_root = _copy_audit_repo(tmp_path / "repo")
    plan_path = copied_root / "evals/rag/v0.2/m5d-b2-experiment-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["scorer_contract"]["implementation_sha256"] = "0" * 64
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="scorer-implementation hash mismatch"):
        freeze.audit_m5d_b2_preregistration(copied_root)


def test_tampered_p4_schema_is_rejected(tmp_path: Path) -> None:
    freeze = _module(FREEZE_MODULE)
    copied_root = _copy_audit_repo(tmp_path / "repo")
    schema_path = copied_root / "evals/rag/v0.2/scorer-v2/p4-output.schema.json"
    schema_path.write_bytes(schema_path.read_bytes() + b" \n")

    with pytest.raises(ValueError, match="P4 output schema SHA256 mismatch"):
        freeze.audit_m5d_b2_preregistration(copied_root)


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
    assert plan["candidate"]["structured_terminal_knowledge_responses_per_turn"] == 1
    assert plan["candidate"]["candidate_specific_repair_generations"] == 0
    assert plan["candidate"]["evaluation_labels_or_expected_facts_exposed_to_model"] is False
    assert plan["candidate"]["agent_prompt_version"] == "text-agent-system-p4-evidence-linked-v1"
    assert plan["candidate"]["grounding_finalizer_version"] == (
        "evidence-linked-extractive-single-pass-v1"
    )
    validation = plan["candidate"]["validation"]
    assert validation["handle_must_belong_to_supplied_selected_evidence"]
    assert validation["supporting_excerpt_must_be_an_exact_source_substring"]
    assert validation["claim_text_must_be_a_nonempty_exact_substring_of_supporting_excerpt"]
    assert validation["substring_matching"] == "literal_case_sensitive"
    assert plan["candidate"]["explicit_limitation"] == (
        "Extractive validation proves the rendered claim text occurs in the cited source "
        "excerpt and that the excerpt comes from supplied evidence; it does not establish "
        "every possible contextual interpretation of that source. Benchmark relevance and "
        "scorer metrics remain the quality evaluation."
    )
    assert plan["quality_floors"] == {
        "citation_precision_minimum": 0.95,
        "citation_precision_requires_nonzero_denominator": True,
        "labeled_groundedness_minimum": 0.9,
        "labeled_groundedness_requires_nonzero_denominator": True,
        "unsupported_recognized_fact_rate_maximum": 0.1,
        "expected_fact_coverage_minimum": 0.7,
        "zero_fabricated_or_non_supplied_evidence_handles": True,
        "trust_invariant_is_additional_to_quality_floors": True,
    }
    assert "application_under_test_sha" in plan["run_identity"]["required_fields"]
    assert "evaluation_harness_sha" in plan["run_identity"]["required_fields"]
    assert "grounding_finalizer_version" in plan["run_identity"]["required_fields"]
    assert plan["resume_identity"]["incompatible_identity_fails_closed"] is True
    assert plan["resume_identity"]["completed_cases_are_never_replayed"] is True
    assert plan["stage4_dev_regression"]["run_only_if_p4_passes_every_rag_quality_floor"]
    assert plan["stage4_dev_regression"]["commerce_authority_preserved"] is True
    assert plan["stage4_dev_regression"]["scope_rule_reason"] == (
        "Stage 4 DEV includes Commerce-tool tasks; authoritative Commerce facts must not be "
        "converted into fabricated knowledge citations."
    )


def test_p4_extractive_mode_is_knowledge_specific_and_bypasses_tool_answers() -> None:
    plan = json.loads(
        (ROOT / "evals/rag/v0.2/m5d-b2-experiment-plan.json").read_text(encoding="utf-8")
    )
    candidate = plan["candidate"]
    mode = candidate["p4_extractive_mode"]

    assert mode["activation_predicate"] == {
        "selected_knowledge_evidence_present": True,
        "commerce_tool_call_executed_in_turn": False,
    }
    assert mode["knowledge_terminal_answer"]["response_schema"] == candidate["schema_path"]
    assert mode["knowledge_terminal_answer"]["apply_extractive_validator"] is True
    assert mode["no_selected_knowledge_evidence"] == {
        "p4_extractive_mode_active": False,
        "fabricate_evidence_handles": False,
        "force_p4_claim_schema": False,
        "preserve_existing_agent_prompt_and_tool_path": True,
    }
    assert mode["commerce_tool_path"] == {
        "tool_call_uses_existing_validation_authorization_and_execution": True,
        "valid_tool_execution_marks_turn_tool_involved": True,
        "p4_extractive_mode_deactivated_after_tool": True,
        "terminal_answer_mode": "existing_plain_tool_result_answer_path",
        "same_p4_system_prompt": True,
        "p4_structured_schema_applied_to_terminal_answer": False,
        "p4_extractive_validator_applied_to_terminal_answer": False,
        "existing_tool_definitions_unchanged": True,
        "existing_tool_authorization_unchanged": True,
        "additional_routing_generations": 0,
        "additional_tool_answer_to_json_conversion_generations": 0,
    }
    assert mode["structured_response_emits_tool_calls"]["follow_existing_bounded_tool_loop"]
    assert mode["structured_response_emits_tool_calls"]["post_tool_terminal_path"] == (
        "existing_plain_tool_result_answer_path"
    )
    assert (
        mode["structured_response_emits_tool_calls"]["second_final_answer_for_json_conversion"]
        is False
    )
    assert candidate["candidate_specific_repair_generations"] == 0
    assert plan["frozen_environment"]["tool_set_unchanged"] is True
    assert plan["frozen_environment"]["tool_authorization_unchanged"] is True
    assert plan["frozen_environment"]["model_tool_and_runtime_budgets_unchanged"] is True
    assert plan["frozen_environment"]["public_application_path"] is True
    assert plan["production_boundary"]["production_tool_set_or_authorization_changed"] is False
    assert candidate["prompt_path_distinction"] == {
        "retrieved_policy_or_company_knowledge": "use the P4 evidence-linked extractive claims contract",
        "live_commerce_facts": "use authoritative Commerce tool results and normal customer-facing answer behavior",
        "benchmark_answer_keys_exposed": False,
    }
    fields = set(plan["observability"]["required_sanitized_trace_fields"])
    assert plan["observability"]["p4_extractive_mode_reason_values"] == [
        "selected_evidence_knowledge_path",
        "no_selected_knowledge_evidence",
        "commerce_tool_call_emitted",
        "deactivated_after_commerce_tool",
        "terminal_tool_answer_bypassed_validator",
        "terminal_knowledge_answer_validated",
        "malformed_or_invalid_structured_knowledge_output",
        "all_claims_rejected_safe_fallback",
    ]
    assert {
        "p4_extractive_mode_active",
        "p4_extractive_mode_reason",
        "tool_path_entered",
        "p4_extractive_mode_deactivated_after_tool",
    } <= fields
    assert {
        "selected evidence: P4 structured knowledge path",
        "no selected evidence: existing path",
        "tool call emitted: existing tool path",
        "terminal tool-derived answer: P4 validator not applied",
        "terminal knowledge answer: P4 validator applied",
        "malformed or invalid structured knowledge output",
        "fallback after all knowledge claims are rejected",
    } <= set(plan["observability"]["diagnostic_distinctions"])


def test_p4_schema_and_plan_freeze_the_literal_extractive_chain_without_answer_keys() -> None:
    plan = json.loads(
        (ROOT / "evals/rag/v0.2/m5d-b2-experiment-plan.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "evals/rag/v0.2/scorer-v2/p4-output.schema.json").read_text(encoding="utf-8")
    )

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["claims"]
    assert "citations" not in schema["properties"]
    assert not {"expected_answer", "expected_facts", "aliases"} & set(schema["properties"])
    claim = schema["$defs"]["claim"]
    assert claim["required"] == ["claim_text", "evidence_handle", "supporting_excerpt"]
    assert claim["additionalProperties"] is False
    assert plan["candidate"]["validation_chain"] == [
        "valid structured schema",
        "server-issued handle belongs to supplied selected evidence",
        "nonempty supporting excerpt is a literal exact substring of that evidence source",
        "nonempty claim text is a literal exact substring of the supporting excerpt",
    ]


def test_future_p4_inference_requires_green_ci_on_exact_freeze_commit() -> None:
    freeze = _module(FREEZE_MODULE)
    commit_sha = "a" * 40
    jobs = dict.fromkeys(freeze.REQUIRED_HOSTED_CI_JOBS, "success")
    authorization = {
        "repo_root": ROOT,
        "freeze_commit_sha": commit_sha,
        "hosted_ci_run_id": 123,
        "hosted_ci_head_sha": commit_sha,
        "hosted_ci_conclusion": "success",
        "job_conclusions": jobs,
    }

    with pytest.raises(ValueError, match="hosted CI run ID"):
        freeze.require_p4_inference_authorized(**{**authorization, "hosted_ci_run_id": None})
    with pytest.raises(ValueError, match="freeze commit"):
        freeze.require_p4_inference_authorized(**{**authorization, "freeze_commit_sha": None})
    with pytest.raises(ValueError, match="exact freeze commit"):
        freeze.require_p4_inference_authorized(**{**authorization, "hosted_ci_head_sha": "b" * 40})
    with pytest.raises(ValueError, match="successful hosted CI"):
        freeze.require_p4_inference_authorized(
            **{**authorization, "hosted_ci_conclusion": "failure"}
        )
    with pytest.raises(ValueError, match="required jobs"):
        freeze.require_p4_inference_authorized(
            **{**authorization, "job_conclusions": {"quality": "success"}}
        )

    freeze.require_p4_inference_authorized(**authorization)


def test_future_inference_authorization_reaudits_scorer_implementation(
    tmp_path: Path,
) -> None:
    scorer = _audit()
    freeze = _module(FREEZE_MODULE)
    copied_root = _copy_audit_repo(tmp_path / "repo")
    manifest = json.loads(
        (copied_root / "evals/rag/v0.2/scorer-v2/manifest.json").read_text(encoding="utf-8")
    )
    implementation = copied_root / manifest["scorer_implementation_path"]
    implementation.write_bytes(implementation.read_bytes() + b"\n# unauthorized drift\n")
    commit_sha = "a" * 40
    jobs = dict.fromkeys(freeze.REQUIRED_HOSTED_CI_JOBS, "success")

    with pytest.raises(scorer.ScorerV2Error, match="scorer implementation SHA256 mismatch"):
        freeze.require_p4_inference_authorized(
            repo_root=copied_root,
            freeze_commit_sha=commit_sha,
            hosted_ci_run_id=123,
            hosted_ci_head_sha=commit_sha,
            hosted_ci_conclusion="success",
            job_conclusions=jobs,
        )
