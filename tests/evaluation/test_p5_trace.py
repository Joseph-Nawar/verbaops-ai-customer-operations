from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

import verbaops.evaluation.p5_trace as p5_trace_module
from verbaops.agent.p4_grounding import empty_p4_response_diagnostics, finalize_p4_response
from verbaops.evaluation.p5_trace import (
    P5TraceStore,
    frozen_p5_observability_contract,
    project_p5_diagnostics,
    verify_p5_trace_records,
)
from verbaops.retrieval.grounding import CitationFinalizer


def _plan() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            (Path(__file__).parents[2] / "evals/rag/v0.2/m5d-b2-p5-experiment-plan.json").read_text(
                encoding="utf-8"
            )
        ),
    )


def _run_dir(root: Path, run_id: str = "canonical-M0-P5-test") -> Path:
    return root / run_id


def test_p5_trace_constants_match_frozen_plan_and_store_exact_fields(tmp_path: Path) -> None:
    plan = _plan()
    observability = plan["observability"]
    fields, transport, response_format_attached, candidate_label = (
        frozen_p5_observability_contract()
    )

    assert fields == frozenset(observability["required_sanitized_trace_fields"])
    assert transport == plan["knowledge_terminal_output_transport"]
    assert (
        response_format_attached
        is plan["knowledge_request"]["provider_response_format_attached"]
        is False
    )
    assert observability["provider_response_format_attached_for_knowledge"] is False
    assert candidate_label == observability["artifact_candidate_label"] == "P5"

    p4 = finalize_p4_response('{"claims": []}', [], CitationFinalizer())
    diagnostics = project_p5_diagnostics(
        p4.diagnostics(), knowledge_mode_active=True, tool_path_entered=False
    )
    assert set(diagnostics) == fields
    assert diagnostics["knowledge_mode_active"] is True
    assert diagnostics["knowledge_terminal_output_transport"] == transport
    assert diagnostics["provider_response_format_attached"] is False
    assert diagnostics["json_parse_success"] is True
    assert diagnostics["schema_validation_result"] is True

    store = P5TraceStore(_run_dir(tmp_path), "canonical-M0-P5-test")
    artifact = store.write(uuid4(), diagnostics)
    assert artifact.relative_path.startswith("p5-traces/")
    assert artifact.payload["candidate"] == "P5"
    assert set(artifact.payload["diagnostics"]) == fields


@pytest.mark.parametrize(
    ("tool_path_entered", "knowledge_mode_active"),
    [(False, False), (True, False)],
)
def test_p5_inactive_no_evidence_and_tool_paths_use_uniform_not_applicable_values(
    tmp_path: Path, tool_path_entered: bool, knowledge_mode_active: bool
) -> None:
    diagnostics = project_p5_diagnostics(
        empty_p4_response_diagnostics(),
        knowledge_mode_active=knowledge_mode_active,
        tool_path_entered=tool_path_entered,
    )

    assert diagnostics["tool_path_entered"] is tool_path_entered
    assert diagnostics["extractive_mode_deactivated_after_tool"] is tool_path_entered
    assert diagnostics["raw_terminal_content"] is None
    assert diagnostics["json_parse_success"] is None
    assert diagnostics["json_parse_failure_reason"] is None
    assert diagnostics["schema_validation_result"] is None
    assert diagnostics["proposed_claims"] == []
    assert diagnostics["rendered_final_claims"] == ""
    assert diagnostics["fallback_used"] is False
    store = P5TraceStore(_run_dir(tmp_path), "canonical-M0-P5-test")
    store.write(uuid4(), diagnostics)


@pytest.mark.parametrize(
    ("content", "json_success", "failure_reason", "schema_valid"),
    [
        ("not json", False, "invalid_json", None),
        ("   ", False, "missing_or_blank_terminal_content", None),
        ('{"claims": [], "extra": true}', True, None, False),
    ],
)
def test_p5_trace_distinguishes_terminal_parse_and_schema_states(
    content: str, json_success: bool, failure_reason: str | None, schema_valid: bool | None
) -> None:
    p4 = finalize_p4_response(content, [], CitationFinalizer())
    diagnostics = project_p5_diagnostics(
        p4.diagnostics(), knowledge_mode_active=True, tool_path_entered=False
    )

    assert diagnostics["json_parse_success"] is json_success
    assert diagnostics["json_parse_failure_reason"] == failure_reason
    assert diagnostics["schema_validation_result"] is schema_valid
    assert diagnostics["fallback_used"] is True


def test_p5_trace_creation_needs_no_experiment_plan_inside_runtime_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_module = (
        tmp_path / "runtime" / "site-packages" / "verbaops" / "evaluation" / "p5_trace.py"
    )
    monkeypatch.setattr(p5_trace_module, "__file__", str(runtime_module))

    fields, transport, response_format_attached, _ = frozen_p5_observability_contract()
    diagnostics = project_p5_diagnostics(
        empty_p4_response_diagnostics(), knowledge_mode_active=False, tool_path_entered=False
    )
    run_id = "canonical-M0-P5-runtime-image"
    store = P5TraceStore(_run_dir(tmp_path, run_id), run_id)
    artifact = store.write(uuid4(), diagnostics)

    assert set(diagnostics) == fields
    assert diagnostics["knowledge_terminal_output_transport"] == transport
    assert diagnostics["provider_response_format_attached"] is response_format_attached is False
    assert artifact.path.is_file()


def test_p5_trace_is_path_confined_hash_bound_and_matches_checkpoint_reference(
    tmp_path: Path,
) -> None:
    run_id = "canonical-M0-P5-hash-test"
    agent_run_id = uuid4()
    diagnostics = project_p5_diagnostics(
        empty_p4_response_diagnostics(), knowledge_mode_active=False, tool_path_entered=False
    )
    canonical_root = tmp_path / "evals/rag/v0.2/dev-evidence/canonical"
    canonical_run_directory = canonical_root / run_id
    canonical_store = P5TraceStore(canonical_run_directory, run_id)
    canonical_artifact = canonical_store.write(agent_run_id, diagnostics)
    record = {
        "agent_run_id": str(agent_run_id),
        "p5_diagnostics": canonical_artifact.payload["diagnostics"],
        "p5_trace_artifact": {
            "path": canonical_artifact.relative_path,
            "sha256": canonical_artifact.sha256,
        },
    }
    refs = verify_p5_trace_records(tmp_path, canonical_run_directory, run_id, [record])
    assert refs == [
        {
            "path": (
                f"evals/rag/v0.2/dev-evidence/canonical/{run_id}/{canonical_artifact.relative_path}"
            ),
            "sha256": canonical_artifact.sha256,
        }
    ]
    with pytest.raises(FileExistsError):
        canonical_store.write(agent_run_id, diagnostics)
    with pytest.raises(ValueError, match="canonical P5 run ID"):
        P5TraceStore(tmp_path / "outside", "canonical-M0-P4-not-p5")


def test_p5_trace_rejects_unwhitelisted_or_inconsistent_diagnostics(tmp_path: Path) -> None:
    store = P5TraceStore(_run_dir(tmp_path), "canonical-M0-P5-test")
    diagnostics = project_p5_diagnostics(
        empty_p4_response_diagnostics(), knowledge_mode_active=False, tool_path_entered=False
    )
    diagnostics["authorization_header"] = "Bearer do-not-persist"

    with pytest.raises(ValueError, match="field contract"):
        store.write(uuid4(), diagnostics)

    clean = project_p5_diagnostics(
        empty_p4_response_diagnostics(), knowledge_mode_active=False, tool_path_entered=False
    )
    clean["provider_response_format_attached"] = True
    with pytest.raises(ValueError, match="response_format"):
        store.write(uuid4(), clean)


def test_p5_trace_redacts_secret_shaped_text_and_rejects_mismatched_reference(
    tmp_path: Path,
) -> None:
    run_id = "canonical-M0-P5-redaction"
    run_directory = tmp_path / "evals/rag/v0.2/dev-evidence/canonical" / run_id
    store = P5TraceStore(run_directory, run_id, secrets_to_hide=("private-value",))
    p4 = finalize_p4_response('{"claims": []} private-value', [], CitationFinalizer())
    diagnostics = project_p5_diagnostics(
        p4.diagnostics(), knowledge_mode_active=True, tool_path_entered=False
    )
    agent_run_id = uuid4()
    artifact = store.write(agent_run_id, diagnostics)
    assert "private-value" not in artifact.path.read_text(encoding="utf-8")

    bad_record = {
        "agent_run_id": str(agent_run_id),
        "p5_diagnostics": artifact.payload["diagnostics"],
        "p5_trace_artifact": {"path": artifact.relative_path, "sha256": "0" * 64},
    }
    with pytest.raises(ValueError, match="reference"):
        verify_p5_trace_records(tmp_path, run_directory, run_id, [bad_record])
