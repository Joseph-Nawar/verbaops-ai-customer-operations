from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from verbaops.evaluation.p4_trace import P4TraceStore, verify_p4_trace_records


def _diagnostics() -> dict[str, Any]:
    return {
        "p4_extractive_mode_active": True,
        "p4_extractive_mode_reason": "selected_evidence_no_tool_path",
        "tool_path_entered": False,
        "p4_extractive_mode_deactivated_after_tool": False,
        "raw_structured_response": '{"claims":[]}',
        "parse_success": True,
        "parse_failure_reason": None,
        "proposed_claims": [
            {
                "claim_text": "Returns accepted within 30 days.",
                "evidence_handle": "K1",
                "supporting_excerpt": "Returns accepted within 30 days.",
            }
        ],
        "claim_validation": [
            {
                "index": 0,
                "claim_text": "Returns accepted within 30 days.",
                "evidence_handle": "K1",
                "supporting_excerpt": "Returns accepted within 30 days.",
                "handle_valid": True,
                "excerpt_nonempty": True,
                "excerpt_matches_source": False,
                "claim_nonempty": True,
                "claim_matches_excerpt": True,
                "accepted": False,
                "rejection_reason": "excerpt_mismatch",
            }
        ],
        "accepted_claims": [],
        "rendered_claims": "",
        "final_rendered_answer": "SAFE",
        "fallback_used": True,
        "fallback_reason": "all_claims_rejected",
    }


def _store(tmp_path: Path, run_id: str | None = None) -> P4TraceStore:
    canonical_run_id = run_id or tmp_path.name
    run_directory = tmp_path / canonical_run_id
    return P4TraceStore(run_directory, canonical_run_id)


def test_p4_trace_is_atomically_stored_by_agent_run_id_and_hash_bound(tmp_path: Path) -> None:
    run_id = "canonical-p4-test"
    store = _store(tmp_path, run_id)
    agent_run_id = uuid4()

    path = store.write(agent_run_id, _diagnostics())
    artifact = store.read(agent_run_id)

    assert path == artifact.path
    assert path.name == f"{agent_run_id}.json"
    assert artifact.relative_path == f"p4-traces/{agent_run_id}.json"
    assert artifact.payload["run_id"] == run_id
    assert artifact.payload["agent_run_id"] == str(agent_run_id)
    assert artifact.payload["diagnostics"] == _diagnostics()
    assert len(artifact.sha256) == 64
    assert not list(path.parent.glob("*.tmp"))


def test_p4_trace_rejects_duplicate_agent_run_sidecars(tmp_path: Path) -> None:
    store = _store(tmp_path, "canonical-p4-duplicate")
    agent_run_id = uuid4()
    store.write(agent_run_id, _diagnostics())

    with pytest.raises(FileExistsError):
        store.write(agent_run_id, _diagnostics())


def test_p4_trace_rejects_missing_malformed_and_mismatched_records(tmp_path: Path) -> None:
    store = _store(tmp_path, "canonical-p4-invalid")
    missing_agent_run_id = uuid4()
    with pytest.raises(FileNotFoundError):
        store.read(missing_agent_run_id)

    malformed_agent_run_id = uuid4()
    malformed_path = store.trace_directory / f"{malformed_agent_run_id}.json"
    malformed_path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        store.read(malformed_agent_run_id)

    mismatched_agent_run_id = uuid4()
    mismatched_path = store.trace_directory / f"{mismatched_agent_run_id}.json"
    mismatched_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "some-other-run",
                "agent_run_id": str(mismatched_agent_run_id),
                "diagnostics": _diagnostics(),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="identity"):
        store.read(mismatched_agent_run_id)


def test_p4_trace_rejects_path_traversal_and_unwhitelisted_data(tmp_path: Path) -> None:
    store = _store(tmp_path, "canonical-p4-whitelist")

    with pytest.raises(ValueError):
        store.write("../outside", _diagnostics())  # type: ignore[arg-type]

    unsafe = _diagnostics()
    unsafe["conversation_history"] = "unrelated customer data"
    with pytest.raises(ValueError, match="not allowed"):
        store.write(uuid4(), unsafe)


def test_p4_trace_rejects_malformed_diagnostic_types(tmp_path: Path) -> None:
    store = _store(tmp_path, "canonical-p4-types")
    diagnostics = _diagnostics()
    diagnostics["parse_success"] = "true"

    with pytest.raises(ValueError, match="malformed"):
        store.write(uuid4(), diagnostics)


def test_p4_trace_rejects_validation_reason_that_disagrees_with_handle_state(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, "canonical-p4-validation-state")
    diagnostics = _diagnostics()
    diagnostics["claim_validation"][0]["rejection_reason"] = "claim_not_substring"

    with pytest.raises(ValueError, match="malformed"):
        store.write(uuid4(), diagnostics)


def test_p4_trace_redacts_credential_shaped_values_before_persistence(tmp_path: Path) -> None:
    store = _store(tmp_path, "canonical-p4-redaction")
    agent_run_id = uuid4()
    diagnostics = _diagnostics()
    secret_marker = "gsk_test-secret-value-123456789"
    diagnostics["raw_structured_response"] = json.dumps({"api_key": secret_marker})

    path = store.write(agent_run_id, diagnostics)
    contents = path.read_text(encoding="utf-8")

    assert secret_marker not in contents
    assert "[redacted]" in contents


def test_p4_checkpoint_trace_references_are_hash_verified(tmp_path: Path) -> None:
    run_id = "canonical-M0-P4-trace-verification"
    run_directory = tmp_path / "evals/rag/v0.2/dev-evidence/canonical" / run_id
    store = P4TraceStore(run_directory, run_id)
    agent_run_id = uuid4()
    store.write(agent_run_id, _diagnostics())
    artifact = store.read(agent_run_id)
    record = {
        "agent_run_id": str(agent_run_id),
        "p4_trace_artifact": {"path": artifact.relative_path, "sha256": artifact.sha256},
        "p4_diagnostics": artifact.payload["diagnostics"],
    }

    refs = verify_p4_trace_records(tmp_path, run_directory, run_id, [record])

    assert refs == [
        {
            "path": (
                f"evals/rag/v0.2/dev-evidence/canonical/{run_id}/p4-traces/{agent_run_id}.json"
            ),
            "sha256": artifact.sha256,
        }
    ]
    changed_record = {
        **record,
        "p4_trace_artifact": {"path": artifact.relative_path, "sha256": "0" * 64},
    }
    with pytest.raises(ValueError, match="does not match sidecar bytes"):
        verify_p4_trace_records(tmp_path, run_directory, run_id, [changed_record])
    store.write(uuid4(), _diagnostics())
    with pytest.raises(ValueError, match="exactly match checkpoint observations"):
        verify_p4_trace_records(tmp_path, run_directory, run_id, [record])


def test_p4_checkpoint_trace_verification_rejects_duplicate_agent_ids(tmp_path: Path) -> None:
    run_id = "canonical-M0-P4-duplicate-agent"
    run_directory = tmp_path / "evals/rag/v0.2/dev-evidence/canonical" / run_id
    store = P4TraceStore(run_directory, run_id)
    agent_run_id = uuid4()
    store.write(agent_run_id, _diagnostics())
    artifact = store.read(agent_run_id)
    record = {
        "agent_run_id": str(agent_run_id),
        "p4_trace_artifact": {"path": artifact.relative_path, "sha256": artifact.sha256},
        "p4_diagnostics": artifact.payload["diagnostics"],
    }

    with pytest.raises(ValueError, match="duplicate agent run ID"):
        verify_p4_trace_records(tmp_path, run_directory, run_id, [record, record])


def test_p4_checkpoint_trace_verification_rejects_unrecognized_sidecar_files(
    tmp_path: Path,
) -> None:
    run_id = "canonical-M0-P4-orphan-temporary"
    run_directory = tmp_path / "evals/rag/v0.2/dev-evidence/canonical" / run_id
    store = P4TraceStore(run_directory, run_id)
    (store.trace_directory / ".abandoned.tmp").write_text("partial sidecar", encoding="utf-8")

    with pytest.raises(ValueError, match="unrecognized files"):
        verify_p4_trace_records(tmp_path, run_directory, run_id, [])
