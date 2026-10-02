"""Frozen P5 plan audit and fail-closed authorization for its one canonical DEV run."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from verbaops.evaluation.m5d_b2_preregistration import (
    REQUIRED_HOSTED_CI_JOBS,
    audit_m5d_b2_p4_closeout,
)
from verbaops.evaluation.rag_v02_scorer_v2 import audit_scorer_v2

P5_PLAN_PATH = Path("evals/rag/v0.2/m5d-b2-p5-experiment-plan.json")
P5_PLAN_SHA256 = "e700ec31f157f47837489fc2d26e1296388405f447701286adc899d7b42fc20e"
P5_CANDIDATE_ID = "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS"
P5_RUN_ID = re.compile(r"canonical-M0-P5-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\Z")
P5_FINAL_RUN_ID = "canonical-M0-P5-20261002T085922Z-80872fc6"
P5_FINAL_IDENTITY_SHA256 = "62c95ac2e893cdab7aaf3f076e6599610d0e15f5a4f1725f10b283cdd52dd58f"
P5_IMPLEMENTATION_FREEZE_SHA = "16fac0f5d416961eea7858a7fd54f220bfef3b32"
P5_FINAL_CLASSIFICATION = "P5_EXECUTION_INELIGIBLE_GROQ_TOOL_USE_FAILED"
P5_CLOSEOUT_SHA256 = "ca6c9c2350767e610f76ccad583709237b760370831f34d3305814d3c8e02bb2"
P5_FINAL_ARTIFACT_SHA256 = {
    "grounded_cases.jsonl": "3f4e788b83981dd94361ae999581da8d9a42db422d30ed6ac6f25b2b3fefcea2",
    "grounded_cases.jsonl.identity.json": "ef22ffd93f2f1fe16cab15e81e5be8a4fd0856bafa6a81d23f1a6f7d87725175",
    "interruption.json": "41753b0da3689590a3559edec6ba2f4929976f05c0e46816f95f7f48cdf63dbc",
    "metadata.json": "18b7ac30c658c36ede9c9b310f6ababd088678bdea672a34cb91f5d97791c757",
    "run-summary.json": "4072d1dd7b1fadb89f01cad547844b0d2304809a5714124bd9f4211a4b0c3a00",
    "p5-traces/cd724cdc-2d32-4936-a989-9525cec5fb0c.json": (
        "53f651bc6a8e2aa942761952fbb6cd7c92f8ac869fed00b9ac4401f6227f2279"
    ),
    "p5-traces/a6089d66-d3a7-4c7b-a7d6-2903f0afd0a8.json": (
        "a548faec782059ad0d5f8d8bb23b274325c7ed94f6bd2b3577cefdb6972cdb5e"
    ),
}
P5_CANONICAL_NAMESPACE = Path("evals/rag/v0.2/dev-evidence/canonical")
REQUIRED_P5_HOSTED_CI_JOBS = REQUIRED_HOSTED_CI_JOBS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _p5_run_directories(root: Path) -> list[Path]:
    canonical_root = root / P5_CANONICAL_NAMESPACE
    if canonical_root.is_symlink():
        raise ValueError("P5 canonical run namespace contains a symlink")
    if not canonical_root.exists():
        return []
    return sorted(
        path
        for path in canonical_root.iterdir()
        if path.name.startswith("canonical-M0-P5-") and path.is_dir()
    )


def require_p5_canonical_run_directory(root: Path, run_directory: Path, *, run_id: str) -> Path:
    """Require a P5 directory directly below the one frozen canonical namespace."""

    if not isinstance(run_id, str) or P5_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("canonical M0 P5 run ID is required")
    canonical_root = root / P5_CANONICAL_NAMESPACE
    path_components = [root]
    path_components.extend(
        root.joinpath(*P5_CANONICAL_NAMESPACE.parts[:index])
        for index in range(1, len(P5_CANONICAL_NAMESPACE.parts) + 1)
    )
    if any(path.is_symlink() for path in path_components) or run_directory.is_symlink():
        raise ValueError("canonical P5 namespace may not contain symlink paths")
    resolved_root = root.resolve()
    resolved_canonical_root = canonical_root.resolve()
    resolved_run_directory = run_directory.resolve()
    if not resolved_canonical_root.is_relative_to(resolved_root):
        raise ValueError("canonical P5 namespace escapes the repository")
    if resolved_run_directory != (resolved_canonical_root / run_id):
        raise ValueError("P5 run directory must be directly in the canonical P5 namespace")
    return resolved_run_directory


def audit_m5d_b2_p5_preregistration(root: Path) -> dict[str, Any]:
    """Check the immutable P5 plan, scorer-v2 contract, and closed P4 evidence."""

    plan_path = root / P5_PLAN_PATH
    if not plan_path.is_file() or _sha256(plan_path) != P5_PLAN_SHA256:
        raise ValueError("P5 experiment plan hash does not match the frozen preregistration")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    execution = plan.get("execution", {})
    environment = plan.get("frozen_environment", {})
    candidate = plan.get("candidate", {})
    request = plan.get("knowledge_request", {})
    transport = plan.get("knowledge_terminal_output_transport")
    if plan.get("candidate_ids") != [P5_CANDIDATE_ID]:
        raise ValueError("P5 plan must preregister exactly one P5 candidate")
    if execution.get("split") != "dev" or execution.get("case_count") != 96:
        raise ValueError("P5 plan must target exactly 96 DEV cases")
    if execution.get("release_holdout_access_allowed") is not False:
        raise ValueError("P5 plan must prohibit release holdout access")
    if execution.get("selection_artifact_allowed") is not False:
        raise ValueError("P5 plan must prohibit selection.json")
    if execution.get("canonical_p5_inference_enabled_in_this_pr") is not False:
        raise ValueError("P5 plan must remain preregistration-only before implementation")
    if execution.get("provider_inference_in_this_pr") is not False:
        raise ValueError("P5 plan must prohibit provider inference in implementation work")
    if (
        candidate.get("id") != P5_CANDIDATE_ID
        or candidate.get("status") != "preregistered_not_implemented"
    ):
        raise ValueError("P5 candidate plan status or ID changed")

    expected_environment = {
        "dataset_sha256": "398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595",
        "knowledge_manifest_sha256": "26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660",
        "retrieval_profile_version": "knowledge-retrieval-v1.1",
        "retrieval_strategy": "hybrid_rrf",
        "final_evidence_count": 5,
        "evidence_gate": "G2_TOP_EVIDENCE_CROSS_ENCODER",
        "evidence_gate_threshold": 0.2554669,
        "model_candidate": "M0",
        "model": "groq/openai/gpt-oss-120b",
        "capability_alias": "agent-fast",
    }
    if any(environment.get(field) != value for field, value in expected_environment.items()):
        raise ValueError("P5 frozen environment differs from its preregistration")
    if (
        transport != "prompt_json_plain_content_no_response_format"
        or request.get("tool_choice") != "auto"
        or request.get("existing_tools") is not True
        or request.get("provider_response_format_attached") is not False
        or request.get("response_format") is not None
    ):
        raise ValueError("P5 knowledge request transport differs from its preregistration")
    if candidate.get("agent_prompt_version") != "text-agent-system-p4-evidence-linked-v1":
        raise ValueError("P5 prompt version differs from the frozen P4 prompt")
    prompt_path = root / "src/verbaops/agent/prompts/system_p4_evidence_linked_v1.txt"
    if candidate.get("agent_prompt_sha256") != _sha256(prompt_path):
        raise ValueError("P5 prompt bytes differ from the frozen prompt")

    p4_closeout = audit_m5d_b2_p4_closeout(root)
    scorer = audit_scorer_v2(root)
    scorer_contract = plan.get("scorer_contract", {})
    manifest = scorer["manifest"]
    scorer_values = {
        "version": manifest["scorer_version"],
        "definition_commit_sha": manifest["scorer_frozen_at_commit_sha"],
        "implementation_sha256": manifest["scorer_implementation_sha256"],
        "manifest_sha256": _sha256(root / "evals/rag/v0.2/scorer-v2/manifest.json"),
        "fixture_sha256": manifest["fixture_data_sha256"],
        "spec_sha256": manifest["scorer_spec_sha256"],
    }
    if any(scorer_contract.get(field) != value for field, value in scorer_values.items()):
        raise ValueError("P5 scorer-v2 hashes differ from the committed scorer contract")
    schema_path = root / plan["local_output_contract"]["schema_path"]
    if plan["local_output_contract"].get("schema_sent_to_provider") is not False or plan[
        "local_output_contract"
    ].get("schema_sha256") != _sha256(schema_path):
        raise ValueError("P5 local output schema differs from the frozen contract")
    dataset_path = root / "evals/rag/v0.2/questions.jsonl"
    manifest_path = root / "knowledge/novacommerce/manifest.json"
    if _sha256(dataset_path) != environment["dataset_sha256"]:
        raise ValueError("P5 dataset hash differs from the frozen contract")
    if _sha256(manifest_path) != environment["knowledge_manifest_sha256"]:
        raise ValueError("P5 knowledge manifest hash differs from the frozen contract")
    if plan.get("quality_floors") != {
        "citation_precision_minimum": 0.95,
        "citation_precision_requires_nonzero_denominator": True,
        "labeled_groundedness_minimum": 0.9,
        "labeled_groundedness_requires_nonzero_denominator": True,
        "unsupported_recognized_fact_rate_maximum": 0.1,
        "expected_fact_coverage_minimum": 0.7,
        "zero_fabricated_or_non_supplied_evidence_handles": True,
        "trust_invariant_is_additional_to_quality_floors": True,
    }:
        raise ValueError("P5 quality floors differ from the frozen contract")
    selection_present = (root / "evals/rag/v0.2/selection.json").exists()
    if selection_present:
        raise ValueError("selection.json is prohibited during P5")

    return {
        "candidate_id": P5_CANDIDATE_ID,
        "split": "dev",
        "case_count": 96,
        "plan_sha256": P5_PLAN_SHA256,
        "p4_closeout_classification": p4_closeout["classification"],
        "release_holdout_access_allowed": False,
        "selection_artifact_allowed": False,
        "selection_json_present": False,
        "scorer_version": scorer_values["version"],
        "scorer_hashes": scorer_values,
        "schema_sha256": _sha256(schema_path),
        "dataset_sha256": _sha256(dataset_path),
        "knowledge_manifest_sha256": _sha256(manifest_path),
    }


def _p5_find_artifact_references(value: Any, target: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("path") == target:
            found.append(value)
        for item in value.values():
            found.extend(_p5_find_artifact_references(item, target))
    elif isinstance(value, list):
        for item in value:
            found.extend(_p5_find_artifact_references(item, target))
    return found


def audit_m5d_b2_p5_closeout(root: Path) -> dict[str, Any]:
    """Validate the immutable terminal P5 execution-ineligible evidence package."""

    root = root.resolve()
    run_dir = require_p5_canonical_run_directory(
        root,
        root / P5_CANONICAL_NAMESPACE / P5_FINAL_RUN_ID,
        run_id=P5_FINAL_RUN_ID,
    )
    if [path.name for path in _p5_run_directories(root)] != [P5_FINAL_RUN_ID]:
        raise ValueError("canonical P5 run namespace does not match the final closeout")

    plan_path = root / P5_PLAN_PATH
    if not plan_path.is_file() or _sha256(plan_path) != P5_PLAN_SHA256:
        raise ValueError("P5 closeout experiment plan hash mismatch")
    closeout_path = run_dir / "p5-closeout.json"
    if not closeout_path.is_file() or _sha256(closeout_path) != P5_CLOSEOUT_SHA256:
        raise ValueError("P5 closeout artifact hash mismatch")
    try:
        closeout = json.loads(closeout_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("P5 closeout artifact is malformed") from error

    expected_closeout = {
        "run_id": P5_FINAL_RUN_ID,
        "run_identity_sha256": P5_FINAL_IDENTITY_SHA256,
        "classification": P5_FINAL_CLASSIFICATION,
        "candidate": P5_CANDIDATE_ID,
        "completed_cases": 2,
        "expected_cases": 96,
        "completed_case_ids": ["m5d-v02-shipping-001", "m5d-v02-shipping-002"],
        "blocked_case_id": "m5d-v02-shipping-003",
        "implementation_freeze_sha": P5_IMPLEMENTATION_FREEZE_SHA,
        "application_under_test_sha": P5_IMPLEMENTATION_FREEZE_SHA,
        "evaluation_harness_sha": P5_IMPLEMENTATION_FREEZE_SHA,
        "p5_experiment_plan_sha256": P5_PLAN_SHA256,
        "public_http_status": 503,
        "runner_retry_after_failure": False,
        "provider_internal_request_or_retry_count": "UNKNOWN",
        "quality_metrics": "NOT_COMPUTED",
        "scoreable": False,
        "scoring_status": "NOT_SCORED_INCOMPLETE_EXECUTION",
        "report_generated": False,
        "release_holdout_executed": False,
        "selection_json_present": False,
        "stage4_dev_eligible": False,
        "m5d_c_started": False,
        "stage6_started": False,
        "trace_sidecar_count": 2,
        "trace_sidecars_hash_verified": True,
        "artifact_references_verified": True,
        "provider_response_format_attached": False,
        "quality_eligibility_conclusion": (
            "NONE; incomplete execution does not establish quality-floor results"
        ),
    }
    for field, expected in expected_closeout.items():
        if closeout.get(field) != expected:
            raise ValueError(f"P5 closeout field mismatch: {field}")
    provider_error = closeout.get("provider_error")
    if not isinstance(provider_error, dict) or any(
        provider_error.get(field) != value
        for field, value in {
            "provider": "Groq",
            "http_status": 400,
            "error_type": "invalid_request_error",
            "error_code": "tool_use_failed",
            "failed_generation_field_present": True,
            "failed_generation_content_persisted": False,
            "parameter": "UNKNOWN",
            "rate_limit_marker_at_failure": False,
            "response_format_marker_in_error_event": False,
        }.items()
    ):
        raise ValueError("P5 closeout provider failure evidence mismatch")
    hosted_ci = closeout.get("hosted_ci")
    if hosted_ci != {
        "conclusion": "success",
        "head_sha": P5_IMPLEMENTATION_FREEZE_SHA,
        "job_conclusions_sha256": "9c796c8222820b55b4b7c1fb3f6ae3db427e27dc7c3039abb26f30067f92637d",
        "run_id": 36984148887,
    }:
        raise ValueError("P5 closeout hosted-CI provenance mismatch")

    run_relative = f"{P5_CANONICAL_NAMESPACE.as_posix()}/{P5_FINAL_RUN_ID}"
    expected_run_artifacts = {
        f"{run_relative}/{relative}": digest
        for relative, digest in P5_FINAL_ARTIFACT_SHA256.items()
    }
    closeout_references = closeout.get("artifacts")
    expected_closeout_references = {
        path: digest
        for path, digest in expected_run_artifacts.items()
        if not path.endswith("/run-summary.json")
    }
    if not isinstance(closeout_references, list):
        raise ValueError("P5 closeout artifact reference list is missing")
    closeout_reference_map = {
        item.get("path"): item.get("sha256")
        for item in closeout_references
        if isinstance(item, dict)
    }
    if (
        len(closeout_references) != len(expected_closeout_references)
        or closeout_reference_map != expected_closeout_references
    ):
        raise ValueError("P5 closeout artifact references do not match the frozen artifact set")
    from verbaops.evaluation.m5d_run_identity import (
        run_identity_sha256,
        verify_artifact_references,
    )

    verify_artifact_references(root, closeout_references)
    for relative, expected_sha in P5_FINAL_ARTIFACT_SHA256.items():
        artifact_path = run_dir / relative
        if not artifact_path.is_file() or _sha256(artifact_path) != expected_sha:
            raise ValueError(f"P5 canonical artifact hash mismatch: {relative}")

    checkpoint_path = run_dir / "grounded_cases.jsonl"
    try:
        observations = [
            json.loads(line)
            for line in checkpoint_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("P5 closeout checkpoint is malformed") from error
    expected_case_ids = ["m5d-v02-shipping-001", "m5d-v02-shipping-002"]
    if (
        len(observations) != 2
        or [record.get("case_id") for record in observations] != expected_case_ids
        or any(
            record.get("run_id") != P5_FINAL_RUN_ID
            or record.get("run_identity_sha256") != P5_FINAL_IDENTITY_SHA256
            for record in observations
        )
    ):
        raise ValueError("P5 closeout checkpoint observation identity mismatch")

    identity_sidecar_path = run_dir / "grounded_cases.jsonl.identity.json"
    try:
        identity_sidecar = json.loads(identity_sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("P5 closeout identity sidecar is malformed") from error
    identity = identity_sidecar.get("identity")
    if (
        not isinstance(identity, dict)
        or identity_sidecar.get("run_identity_sha256") != P5_FINAL_IDENTITY_SHA256
        or run_identity_sha256(identity) != P5_FINAL_IDENTITY_SHA256
        or identity.get("run_id") != P5_FINAL_RUN_ID
        or identity.get("implementation_freeze_sha") != P5_IMPLEMENTATION_FREEZE_SHA
        or identity.get("application_under_test_sha") != P5_IMPLEMENTATION_FREEZE_SHA
        or identity.get("evaluation_harness_sha") != P5_IMPLEMENTATION_FREEZE_SHA
        or identity.get("p5_experiment_plan_sha256") != P5_PLAN_SHA256
    ):
        raise ValueError("P5 closeout identity sidecar fingerprint mismatch")

    from verbaops.evaluation.p5_trace import verify_p5_trace_records

    trace_references = verify_p5_trace_records(root, run_dir, P5_FINAL_RUN_ID, observations)
    if len(trace_references) != 2:
        raise ValueError("P5 closeout must contain exactly two matching trace sidecars")
    trace_hashes = {reference["path"]: reference["sha256"] for reference in trace_references}
    expected_trace_hashes = {
        path: digest for path, digest in expected_run_artifacts.items() if "/p5-traces/" in path
    }
    if trace_hashes != expected_trace_hashes:
        raise ValueError("P5 closeout trace sidecar hashes do not match observations")

    summary_path = root / "evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json"
    decision_path = root / "evals/rag/v0.2/dev-decision.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        run_summary = json.loads((run_dir / "run-summary.json").read_text(encoding="utf-8"))
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        interruption = json.loads((run_dir / "interruption.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("P5 closeout milestone evidence is malformed") from error
    if (
        run_summary.get("run_id") != P5_FINAL_RUN_ID
        or run_summary.get("run_identity_sha256") != P5_FINAL_IDENTITY_SHA256
        or run_summary.get("completed_cases") != 2
        or run_summary.get("blocked_case_id") != "m5d-v02-shipping-003"
        or metadata.get("run_id") != P5_FINAL_RUN_ID
        or metadata.get("run_identity_sha256") != P5_FINAL_IDENTITY_SHA256
        or metadata.get("completed_case_count") != 2
        or interruption.get("run_id") != P5_FINAL_RUN_ID
        or interruption.get("run_identity_sha256") != P5_FINAL_IDENTITY_SHA256
        or interruption.get("completed_case_count") != 2
        or interruption.get("blocked_case_id") != "m5d-v02-shipping-003"
        or interruption.get("holdout_executed") is not False
    ):
        raise ValueError("P5 closeout interruption or run metadata mismatch")
    if (run_dir / "report.json").exists():
        raise ValueError("incomplete P5 closeout cannot contain a report or score")
    if (root / "evals/rag/v0.2/selection.json").exists():
        raise ValueError("selection.json is prohibited during M5D-B2")
    if (
        decision.get("canonical_evidence_status") != "COMPLETE"
        or summary.get("canonical_evidence_status") != "COMPLETE"
        or decision.get("status") != "NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE"
        or summary.get("decision_status") != "NO_GROUNDING_CANDIDATE_MEETS_M5D_QUALITY_GATE"
        or decision.get("holdout_executed") is not False
        or summary.get("release_holdout_executed") is not False
        or decision.get("selection_json_present") is not False
        or summary.get("selection_json_present") is not False
        or decision.get("stage_m5d_c_started") is not False
        or summary.get("stage_m5d_c_started") is not False
        or decision.get("stage6_started") is not False
        or summary.get("stage6_started") is not False
        or decision.get("selected_grounding_candidate") is not None
        or summary.get("selected_grounding_candidate") is not None
        or summary.get("grounding_selection", {}).get("selected_candidate") is not None
        or summary.get("grounding_selection", {}).get("final_no_candidate_conclusion") is not True
    ):
        raise ValueError("M5D-B2 final P5 milestone state mismatch")

    expected_candidate_reasons = {
        "P0_CURRENT": "QUALITY_INELIGIBLE",
        "P1_PROMPT_V3": "EXECUTION_INELIGIBLE_AGENT_BUDGET_EXCEEDED",
        "P2_FAIL_CLOSED_CITATIONS": "QUALITY_INELIGIBLE",
        "P3_ONE_REPAIR_THEN_FAIL_CLOSED": "QUALITY_INELIGIBLE",
        "P4_EVIDENCE_LINKED_SINGLE_PASS": (
            "P4_EXECUTION_INELIGIBLE_GROQ_RESPONSE_FORMAT_TOOL_CALLING_INCOMPATIBILITY"
        ),
        "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS": P5_FINAL_CLASSIFICATION,
    }
    if (
        decision.get("grounding_candidate_reasons") != expected_candidate_reasons
        or summary.get("grounding_candidate_reasons") != expected_candidate_reasons
        or summary.get("grounding_selection", {}).get("candidate_reasons")
        != expected_candidate_reasons
    ):
        raise ValueError("M5D-B2 final candidate eligibility reasons mismatch")

    expected_closeout_record = {
        "run_id": P5_FINAL_RUN_ID,
        "classification": P5_FINAL_CLASSIFICATION,
        "execution_eligibility": "INELIGIBLE",
        "run_identity_sha256": P5_FINAL_IDENTITY_SHA256,
        "completed_cases": 2,
        "total_cases": 96,
        "blocked_case_id": "m5d-v02-shipping-003",
        "failure_class": "PROVIDER_GENERATED_TOOL_CALL_REJECTION",
        "scoring_status": "NOT_SCORED_INCOMPLETE_EXECUTION",
        "public_api_http_status": 503,
        "upstream_provider_http_status": 400,
        "upstream_error_type": "invalid_request_error",
        "upstream_error_code": "tool_use_failed",
        "upstream_error_parameter": "UNKNOWN",
        "failed_generation_field_present": True,
        "failed_generation_content_persisted": False,
        "rate_limit_marker_established": False,
        "runner_retry_after_failure": False,
        "provider_internal_request_or_retry_count": "UNKNOWN",
        "quality_metrics": "NOT_COMPUTED",
        "quality_eligibility_conclusion": (
            "NONE; incomplete execution does not establish quality-floor results"
        ),
        "stage4_dev_status": "NOT_RUN_P5_EXECUTION_INELIGIBLE",
        "stage4_dev_eligible": False,
        "m5d_c_eligible": False,
        "m5d_c_started": False,
        "stage6_started": False,
        "release_holdout_executed": False,
        "selection_json_present": False,
        "report_generated": False,
        "trace_sidecar_count": 2,
        "implementation_freeze_sha": P5_IMPLEMENTATION_FREEZE_SHA,
        "application_under_test_sha": P5_IMPLEMENTATION_FREEZE_SHA,
        "evaluation_harness_sha": P5_IMPLEMENTATION_FREEZE_SHA,
        "p5_experiment_plan_sha256": P5_PLAN_SHA256,
    }
    closeout_relative = closeout_path.relative_to(root).as_posix()
    closeout_sha = _sha256(closeout_path)
    allowed_closeout_fields = {*expected_closeout_record, "closeout_artifact"}
    for document in (decision, summary):
        actual_record = document.get("p5_execution_closeout")
        if (
            not isinstance(actual_record, dict)
            or set(actual_record) != allowed_closeout_fields
            or any(
                actual_record.get(field) != expected
                for field, expected in expected_closeout_record.items()
            )
        ):
            raise ValueError("M5D-B2 P5 execution closeout record mismatch")
        references = _p5_find_artifact_references(document, closeout_relative)
        if not references or any(item.get("sha256") != closeout_sha for item in references):
            raise ValueError("P5 closeout artifact hash reference mismatch")
        if document.get("grounding_candidate_reasons", {}).get(P5_CANDIDATE_ID) != (
            P5_FINAL_CLASSIFICATION
        ):
            raise ValueError("P5 final candidate reason is missing from the M5D decision")

    run_records = [
        record
        for document in (decision, summary)
        for record in document.get("canonical_runs", [])
        if isinstance(record, dict) and record.get("run_id") == P5_FINAL_RUN_ID
    ]
    if len(run_records) != 2:
        raise ValueError("M5D-B2 decision and summary must each record canonical P5")
    expected_milestone_artifacts = {
        **expected_run_artifacts,
        closeout_path.relative_to(root).as_posix(): P5_CLOSEOUT_SHA256,
    }
    for record in run_records:
        artifact_references = record.get("artifacts")
        artifact_map = (
            {
                item.get("path"): item.get("sha256")
                for item in artifact_references
                if isinstance(item, dict)
            }
            if isinstance(artifact_references, list)
            else {}
        )
        if (
            record.get("candidate") != P5_CANDIDATE_ID
            or record.get("status") != P5_FINAL_CLASSIFICATION
            or record.get("execution_eligibility") != "INELIGIBLE"
            or record.get("completed_cases") != 2
            or record.get("total_cases") != 96
            or record.get("blocked_case_id") != "m5d-v02-shipping-003"
            or record.get("run_identity_sha256") != P5_FINAL_IDENTITY_SHA256
            or record.get("evaluated_git_sha") != P5_IMPLEMENTATION_FREEZE_SHA
            or record.get("application_under_test_sha") != P5_IMPLEMENTATION_FREEZE_SHA
            or record.get("evaluation_harness_sha") != P5_IMPLEMENTATION_FREEZE_SHA
            or record.get("scoring_status") != "NOT_SCORED_INCOMPLETE_EXECUTION"
            or record.get("scoreable") is not False
            or record.get("metrics") is not None
            or record.get("quality_metrics") != "NOT_COMPUTED"
            or record.get("report_generated") is not False
            or artifact_map != expected_milestone_artifacts
        ):
            raise ValueError("M5D-B2 P5 canonical run decision mismatch")

    summary_candidate = summary.get("grounding_candidates", {}).get(P5_CANDIDATE_ID)
    if (
        not isinstance(summary_candidate, dict)
        or summary_candidate.get("run_id") != P5_FINAL_RUN_ID
        or summary_candidate.get("status") != P5_FINAL_CLASSIFICATION
        or summary_candidate.get("execution_eligibility") != "INELIGIBLE"
        or summary_candidate.get("completed_cases") != 2
        or summary_candidate.get("total_cases") != 96
        or summary_candidate.get("metrics") is not None
        or summary_candidate.get("scoreable") is not False
        or {
            item.get("path"): item.get("sha256")
            for item in summary_candidate.get("artifacts", [])
            if isinstance(item, dict)
        }
        != expected_milestone_artifacts
    ):
        raise ValueError("M5D-B2 P5 candidate summary mismatch")

    summary_sha = hashlib.sha256(summary_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    summary_relative = summary_path.relative_to(root).as_posix()
    summary_references = _p5_find_artifact_references(decision, summary_relative)
    if not summary_references or any(
        item.get("sha256") != summary_sha for item in summary_references
    ):
        raise ValueError("M5D-B2 summary artifact hash reference mismatch")
    return {
        "run_id": P5_FINAL_RUN_ID,
        "run_identity_sha256": P5_FINAL_IDENTITY_SHA256,
        "classification": P5_FINAL_CLASSIFICATION,
        "execution_eligibility": "INELIGIBLE",
        "completed_cases": 2,
        "expected_cases": 96,
        "completed_case_ids": expected_case_ids,
        "blocked_case_id": "m5d-v02-shipping-003",
        "observation_count": len(observations),
        "trace_sidecar_count": len(trace_references),
        "report_generated": False,
        "quality_metrics_computed": False,
        "stage4_dev_eligible": False,
        "m5d_c_eligible": False,
        "release_holdout_executed": False,
        "selection_json_present": False,
        "canonical_evidence_status": "COMPLETE",
        "artifact_hashes_valid": True,
        "p5_closeout_sha256": closeout_sha,
        "summary_sha256": summary_sha,
    }


def _p5_final_closeout_is_recorded(root: Path) -> bool:
    for relative in (
        "evals/rag/v0.2/dev-decision.json",
        "evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json",
    ):
        path = root / relative
        if not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("P5 final decision marker is malformed") from error
        if not isinstance(document, dict):
            raise ValueError("P5 final decision marker is malformed")
        if P5_FINAL_RUN_ID in document.get("canonical_run_ids", []):
            return True
        if any(
            isinstance(record, dict) and record.get("run_id") == P5_FINAL_RUN_ID
            for record in document.get("canonical_runs", [])
        ):
            return True
        record = document.get("p5_execution_closeout")
        if record is not None:
            if (
                not isinstance(record, dict)
                or record.get("run_id") != P5_FINAL_RUN_ID
                or record.get("classification") != P5_FINAL_CLASSIFICATION
            ):
                raise ValueError("P5 final decision marker does not match the terminal closeout")
            return True
        summary_candidate = document.get("grounding_candidates", {}).get(P5_CANDIDATE_ID)
        if (
            isinstance(summary_candidate, dict)
            and summary_candidate.get("run_id") == P5_FINAL_RUN_ID
        ):
            return True
    return False


def require_p5_inference_authorized(
    *,
    repo_root: Path,
    run_id: str,
    freeze_commit_sha: str | None,
    hosted_ci_run_id: int | None,
    hosted_ci_head_sha: str | None,
    hosted_ci_conclusion: str | None,
    job_conclusions: dict[str, str],
) -> None:
    """Authorize the one P5 namespace only on an exact committed green freeze."""

    if not isinstance(run_id, str) or P5_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("canonical M0 P5 run ID is required")
    audit_m5d_b2_p5_preregistration(repo_root)
    directories = _p5_run_directories(repo_root)
    if any(path.is_symlink() for path in directories):
        raise ValueError("P5 canonical run namespace contains a symlink")
    final_run_directory = repo_root / P5_CANONICAL_NAMESPACE / P5_FINAL_RUN_ID
    final_closeout = final_run_directory / "p5-closeout.json"
    if final_closeout.is_file():
        audit_m5d_b2_p5_closeout(repo_root)
    if run_id == P5_FINAL_RUN_ID:
        raise ValueError("canonical P5 run is closed and cannot resume")
    if (
        final_closeout.is_file()
        or final_run_directory.is_dir()
        or _p5_final_closeout_is_recorded(repo_root)
    ):
        raise ValueError("canonical P5 run is closed; no second P5 run is permitted")
    if directories and [path.name for path in directories] != [run_id]:
        raise ValueError("P5 canonical run namespace contains an unrelated run")
    requested_directory = repo_root / P5_CANONICAL_NAMESPACE / run_id
    if (requested_directory / "report.json").exists():
        raise ValueError("completed canonical P5 run cannot resume")
    summary_path = requested_directory / "run-summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("P5 canonical run summary is malformed") from error
        completed_cases = summary.get("completed_cases") if isinstance(summary, dict) else None
        if (
            not isinstance(summary, dict)
            or summary.get("canonical") is not True
            or summary.get("run_id") != run_id
            or isinstance(completed_cases, bool)
            or not isinstance(completed_cases, int)
        ):
            raise ValueError("P5 canonical run summary identity is invalid")
        if completed_cases >= 96:
            raise ValueError("completed canonical P5 run cannot resume")
    if freeze_commit_sha is None or re.fullmatch(r"[a-f0-9]{40}", freeze_commit_sha) is None:
        raise ValueError("P5 requires a committed full implementation freeze SHA")
    if hosted_ci_head_sha != freeze_commit_sha:
        raise ValueError("P5 hosted CI must run on the exact implementation freeze SHA")
    if hosted_ci_conclusion != "success":
        raise ValueError("P5 requires successful hosted CI on the implementation freeze")
    if (
        isinstance(hosted_ci_run_id, bool)
        or not isinstance(hosted_ci_run_id, int)
        or hosted_ci_run_id <= 0
    ):
        raise ValueError("P5 hosted CI run ID must be a positive integer")
    if set(job_conclusions) != set(REQUIRED_P5_HOSTED_CI_JOBS):
        raise ValueError("P5 hosted CI must provide exactly the 16 required jobs")
    failed = [job for job in REQUIRED_P5_HOSTED_CI_JOBS if job_conclusions.get(job) != "success"]
    if failed:
        raise ValueError("P5 required jobs must all succeed: " + ", ".join(failed))

    from verbaops.evaluation.m5d_run_identity import (
        PRE_EXPERIMENT_SHA,
        require_committed_behavior,
    )

    current = require_committed_behavior(repo_root, pre_experiment_sha=PRE_EXPERIMENT_SHA)
    if current != freeze_commit_sha:
        raise ValueError("working-tree HEAD must equal the exact P5 implementation freeze")


__all__ = [
    "P5_CANDIDATE_ID",
    "P5_CANONICAL_NAMESPACE",
    "P5_FINAL_ARTIFACT_SHA256",
    "P5_FINAL_CLASSIFICATION",
    "P5_FINAL_IDENTITY_SHA256",
    "P5_FINAL_RUN_ID",
    "P5_PLAN_PATH",
    "P5_PLAN_SHA256",
    "REQUIRED_P5_HOSTED_CI_JOBS",
    "audit_m5d_b2_p5_closeout",
    "audit_m5d_b2_p5_preregistration",
    "require_p5_canonical_run_directory",
    "require_p5_inference_authorized",
]
