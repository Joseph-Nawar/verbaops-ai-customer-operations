from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from verbaops.agent.versions import (
    GRAPH_RECURSION_LIMIT,
    MAX_MODEL_CALLS,
    MAX_TOOL_CALLS,
    MAX_TOOL_ROUNDS,
    MAX_VALIDATION_REPAIRS,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "evals/rag/v0.2/m5d-b2-p5-experiment-plan.json"
PROMPT_PATH = ROOT / "src/verbaops/agent/prompts/system_p4_evidence_linked_v1.txt"
DOC_PATH = ROOT / "docs/evaluation/stage5-m5d-b2-p5-preregistration.md"


def _load_plan() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(PLAN_PATH.read_text(encoding="utf-8")))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_p5_plan_freezes_only_the_prompt_json_transport_delta() -> None:
    plan = _load_plan()

    assert plan["schema_version"] == "m5d-b2-p5-experiment-plan-v1"
    assert plan["status"] == "preregistration_only_no_results"
    assert plan["candidate_ids"] == ["P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS"]
    assert plan["knowledge_terminal_output_transport"] == (
        "prompt_json_plain_content_no_response_format"
    )

    execution = plan["execution"]
    assert execution["split"] == "dev"
    assert execution["case_count"] == 96
    assert execution["canonical_run_count"] == 1
    assert execution["baseline_reruns"] == []
    assert execution["release_holdout_access_allowed"] is False
    assert execution["selection_artifact_allowed"] is False
    assert execution["provider_inference_in_this_pr"] is False
    assert execution["p5_results_present_in_this_pr"] is False

    environment = plan["frozen_environment"]
    assert environment["dataset_sha256"] == (
        "398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595"
    )
    assert environment["knowledge_manifest_sha256"] == (
        "26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660"
    )
    assert environment["evidence_gate"] == "G2_TOP_EVIDENCE_CROSS_ENCODER"
    assert environment["evidence_gate_threshold"] == 0.2554669
    assert environment["retrieval_profile_version"] == "knowledge-retrieval-v1.1"
    assert environment["retrieval_strategy"] == "hybrid_rrf"
    assert environment["final_evidence_count"] == 5
    assert environment["model_candidate"] == "M0"
    assert environment["model"] == "groq/openai/gpt-oss-120b"
    assert environment["capability_alias"] == "agent-fast"

    scorer = plan["scorer_contract"]
    assert scorer["version"] == "rag-v0.2-scorer-v2"
    assert scorer["definition_commit_sha"] == "fa800f5bfee4ee903905d89bf600642e9ddb0d95"
    assert scorer["implementation_sha256"] == (
        "aa0eff0b165a8d40e22416bad493f432931409ca70d2abee89682966c39df67a"
    )
    assert scorer["fixture_sha256"] == (
        "7dd8662d39b14c71c01fad309341c478401d649f7165ae4ced384053b420675a"
    )
    assert scorer["spec_sha256"] == (
        "55eb54f61be1dfe6536a23f0786021b193e032dfa0fdc760bc2caa6c5688f120"
    )
    assert scorer["manifest_sha256"] == (
        "6a86c9d93f3ab9f53595d99138745311f1f4cad8e2673150be7446d1ecdd5bbb"
    )

    output = plan["local_output_contract"]
    assert output["schema_path"] == "evals/rag/v0.2/scorer-v2/p4-output.schema.json"
    assert output["schema_sha256"] == (
        "c406afdf4100c01328bd86e06d8d4408c25a51a696fb00ff0ea69394ccc625e9"
    )
    assert output["schema_sent_to_provider"] is False
    request = plan["knowledge_request"]
    assert request["client_method"] == "LLMClient.generate"
    assert request["existing_tools"] is True
    assert request["existing_tool_choice"] is True
    assert request["tool_choice"] == "auto"
    assert request["response_format"] is None
    assert request["provider_json_mode"] is False

    candidate = plan["candidate"]
    assert candidate["id"] == "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS"
    assert candidate["status"] == "preregistered_not_implemented"
    assert candidate["agent_prompt_path"] == PROMPT_PATH.relative_to(ROOT).as_posix()
    assert candidate["agent_prompt_version"] == "text-agent-system-p4-evidence-linked-v1"
    assert candidate["agent_prompt_sha256"] == _sha256(PROMPT_PATH)
    assert candidate["agent_graph_version"] == "text-agent-m5d-v1"
    assert candidate["grounding_finalizer_version"] == ("evidence-linked-extractive-single-pass-v1")
    assert candidate["candidate_specific_repair_generations"] == 0

    budgets = plan["runtime_budgets"]
    assert budgets["max_model_calls_per_case"] == MAX_MODEL_CALLS == 4
    assert budgets["max_tool_rounds"] == MAX_TOOL_ROUNDS == 3
    assert budgets["max_tool_calls"] == MAX_TOOL_CALLS == 6
    assert budgets["max_validation_repairs"] == MAX_VALIDATION_REPAIRS == 1
    assert budgets["graph_recursion_limit"] == GRAPH_RECURSION_LIMIT == 20

    quality = plan["quality_floors"]
    assert quality == {
        "citation_precision_minimum": 0.95,
        "citation_precision_requires_nonzero_denominator": True,
        "labeled_groundedness_minimum": 0.90,
        "labeled_groundedness_requires_nonzero_denominator": True,
        "unsupported_recognized_fact_rate_maximum": 0.10,
        "expected_fact_coverage_minimum": 0.70,
        "zero_fabricated_or_non_supplied_evidence_handles": True,
        "trust_invariant_is_additional_to_quality_floors": True,
    }

    identity = plan["run_identity"]
    required_identity_fields = set(identity["required_fields"])
    assert {
        "p5_experiment_plan_sha256",
        "knowledge_terminal_output_transport",
        "tool_choice",
        "local_output_schema_sha256",
        "application_under_test_sha",
        "evaluation_harness_sha",
        "implementation_freeze_sha",
        "hosted_ci_run_id",
        "hosted_ci_head_sha",
        "grounding_candidate",
        "model_revision",
        "evidence_gate",
        "evidence_gate_threshold",
        "agent_prompt_version",
        "agent_graph_version",
        "grounding_finalizer_version",
        "run_id",
    }.issubset(required_identity_fields)
    assert identity["fixed_values"]["tool_choice"] == "auto"

    assert plan["observability"]["required_sanitized_trace_fields"]
    assert (
        "provider_response_format_attached"
        in plan["observability"]["required_sanitized_trace_fields"]
    )
    assert plan["observability"]["provider_response_format_attached_for_knowledge"] is False

    tool_path = plan["tool_path"]
    assert tool_path["existing_tool_definitions_available_on_knowledge_request"] is True
    assert tool_path["extractive_parser_applied_to_tool_terminal_answer"] is False
    parser = plan["terminal_knowledge_parser"]
    assert parser["parse_states"] == [
        "valid_json_valid_schema",
        "blank_content",
        "invalid_json",
        "schema_invalid_json",
    ]
    assert parser["strip_markdown_fences"] is False
    assert parser["json_cleanup_heuristics"] is False
    assert parser["additional_model_calls_on_parse_failure"] == 0
    finalization = plan["extractive_finalization"]
    assert finalization["handle_must_be_supplied_selected_evidence_handle"] is True
    assert finalization["excerpt_must_be_nonempty_exact_case_sensitive_source_substring"] is True
    assert finalization["claim_must_be_nonempty_exact_case_sensitive_excerpt_substring"] is True
    assert finalization["reuse_existing_citation_finalizer"] is True
    assert plan["provider_and_resume_stop_rules"]["provider_protocol_incompatibility"]
    assert plan["stage4_dev_regression"]["execute_in_this_pr"] is False

    doc = DOC_PATH.read_text(encoding="utf-8")
    assert f"P5 experiment plan SHA256: `{_sha256(PLAN_PATH)}`" in doc
    assert "PREREGISTRATION ONLY" in doc
    assert "json mode cannot be combined with tool/function calling" in doc


def test_p4_closeout_and_frozen_plan_remain_unchanged() -> None:
    from verbaops.evaluation.m5d_b2_preregistration import audit_m5d_b2_p4_closeout

    audit = audit_m5d_b2_p4_closeout(ROOT)
    assert audit["classification"] == (
        "P4_EXECUTION_INELIGIBLE_GROQ_RESPONSE_FORMAT_TOOL_CALLING_INCOMPATIBILITY"
    )
    assert audit["completed_cases"] == 1
    assert audit["expected_cases"] == 96
    assert audit["quality_metrics_computed"] is False
    assert audit["artifact_hashes_valid"] is True
    assert audit["release_holdout_executed"] is False
    assert audit["selection_json_present"] is False
    assert audit["p4_closeout_sha256"] == (
        "9c6b9b0a3b51a79a84c6feae94708ea4ac9b8a14293fc7c1ddb1c8acf37adf72"
    )

    frozen_hashes = {
        "src/verbaops/evaluation/rag_v02_scorer_impl.py": (
            "aa0eff0b165a8d40e22416bad493f432931409ca70d2abee89682966c39df67a"
        ),
        "evals/rag/v0.2/scorer-v2/fixtures.json": (
            "7dd8662d39b14c71c01fad309341c478401d649f7165ae4ced384053b420675a"
        ),
        "evals/rag/v0.2/scorer-v2/spec.json": (
            "55eb54f61be1dfe6536a23f0786021b193e032dfa0fdc760bc2caa6c5688f120"
        ),
        "evals/rag/v0.2/scorer-v2/manifest.json": (
            "6a86c9d93f3ab9f53595d99138745311f1f4cad8e2673150be7446d1ecdd5bbb"
        ),
        "evals/rag/v0.2/m5d-b2-experiment-plan.json": (
            "2645e6430f7b936ecda089589213b2cb9828fdc4b23c526d885ff9c353617eee"
        ),
        "evals/rag/v0.2/scorer-v2/p4-output.schema.json": (
            "c406afdf4100c01328bd86e06d8d4408c25a51a696fb00ff0ea69394ccc625e9"
        ),
        "evals/rag/v0.2/questions.jsonl": (
            "398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595"
        ),
        "knowledge/novacommerce/manifest.json": (
            "26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660"
        ),
        "src/verbaops/agent/prompts/system_p4_evidence_linked_v1.txt": (
            "29d5512332a8e0463929c44a2c46d4ff0dc8f5c6e49523db57066856278cada6"
        ),
    }
    for relative_path, expected_sha in frozen_hashes.items():
        assert _sha256(ROOT / relative_path) == expected_sha


def test_final_p5_namespace_is_closed_and_selection_artifact_absent() -> None:
    from verbaops.evaluation.m5d_b2_p5_preregistration import (
        P5_FINAL_RUN_ID,
        audit_m5d_b2_p5_closeout,
    )

    plan = _load_plan()
    canonical_root = ROOT / "evals/rag/v0.2/dev-evidence/canonical"
    assert plan["execution"]["selection_artifact_allowed"] is False
    assert plan["execution"]["release_holdout_access_allowed"] is False
    assert [path.name for path in canonical_root.glob("canonical-M0-P5-*")] == [P5_FINAL_RUN_ID]
    assert audit_m5d_b2_p5_closeout(ROOT)["canonical_evidence_status"] == "COMPLETE"
    assert not (ROOT / "evals/rag/v0.2/selection.json").exists()
