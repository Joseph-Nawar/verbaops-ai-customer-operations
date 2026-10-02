"""Sanitized canonical trace storage for the P5 plain-JSON candidate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from verbaops.evaluation.p4_trace import _sanitize_value

P5_TRACE_FIELDS = frozenset(
    {
        "knowledge_mode_active",
        "knowledge_terminal_output_transport",
        "provider_response_format_attached",
        "tool_path_entered",
        "extractive_mode_deactivated_after_tool",
        "raw_terminal_content",
        "json_parse_success",
        "json_parse_failure_reason",
        "schema_validation_result",
        "proposed_claims",
        "proposed_evidence_handle_per_claim",
        "proposed_excerpt_per_claim",
        "handle_validation_result_per_claim",
        "excerpt_validation_result_per_claim",
        "deterministic_rejection_reason_per_claim",
        "rendered_final_claims",
        "fallback_used",
        "fallback_reason",
    }
)
P5_KNOWLEDGE_TERMINAL_OUTPUT_TRANSPORT = "prompt_json_plain_content_no_response_format"
P5_PROVIDER_RESPONSE_FORMAT_ATTACHED = False
P5_TRACE_CANDIDATE_LABEL = "P5"
_RUN_ID = re.compile(r"canonical-M0-P5-[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_P4_FAILURE_TO_JSON_FAILURE = {
    "invalid_json": "invalid_json",
    "missing_or_blank_terminal_content": "missing_or_blank_terminal_content",
}
_P5_REJECTION_REASONS = {
    "invalid_handle",
    "empty_excerpt",
    "excerpt_mismatch",
    "empty_claim",
    "claim_not_substring",
}
_P5_FALLBACK_REASONS = {
    "invalid_json",
    "invalid_p4_schema",
    "missing_or_blank_terminal_content",
    "all_claims_rejected",
    "citation_finalizer_rejected_claims",
}
_TOP_LEVEL_FIELDS = {"schema_version", "candidate", "run_id", "agent_run_id", "diagnostics"}
_CLAIM_FIELDS = {"claim_text", "evidence_handle", "supporting_excerpt"}


@dataclass(frozen=True, slots=True)
class P5TraceArtifact:
    path: Path
    relative_path: str
    sha256: str
    payload: dict[str, Any]


def frozen_p5_observability_contract() -> tuple[frozenset[str], str, bool, str]:
    """Return runtime-minimal contract constants; never reads repository evaluation files."""

    return (
        P5_TRACE_FIELDS,
        P5_KNOWLEDGE_TERMINAL_OUTPUT_TRANSPORT,
        P5_PROVIDER_RESPONSE_FORMAT_ATTACHED,
        P5_TRACE_CANDIDATE_LABEL,
    )


def project_p5_diagnostics(
    p4_diagnostics: Mapping[str, Any],
    *,
    knowledge_mode_active: bool,
    tool_path_entered: bool,
) -> dict[str, Any]:
    """Project shared P4 parser diagnostics onto the frozen P5 trace vocabulary."""

    if tool_path_entered and knowledge_mode_active:
        raise ValueError("P5 knowledge mode cannot remain active after a Commerce tool")
    if not isinstance(p4_diagnostics, Mapping):
        raise ValueError("P5 trace projection requires parser diagnostics")

    raw_content: str | None = None
    json_parse_success: bool | None = None
    json_parse_failure_reason: str | None = None
    schema_validation_result: bool | None = None
    proposed: list[dict[str, str]] = []
    handles: list[str] = []
    excerpts: list[str] = []
    handle_results: list[bool] = []
    excerpt_results: list[bool | None] = []
    rejection_reasons: list[str | None] = []
    rendered = ""
    fallback_used = False
    fallback_reason: str | None = None

    if knowledge_mode_active:
        raw = p4_diagnostics.get("raw_structured_model_response")
        if raw is not None and not isinstance(raw, str):
            raise ValueError("P5 terminal content is malformed")
        raw_content = raw
        parse_success = p4_diagnostics.get("parse_success")
        parse_failure = p4_diagnostics.get("parse_failure_reason")
        if parse_success is True:
            json_parse_success = True
            schema_validation_result = True
        elif parse_failure == "invalid_p4_schema":
            json_parse_success = True
            schema_validation_result = False
        elif parse_failure in _P4_FAILURE_TO_JSON_FAILURE:
            json_parse_success = False
            json_parse_failure_reason = _P4_FAILURE_TO_JSON_FAILURE[parse_failure]
        else:
            raise ValueError("P5 parser diagnostics are inconsistent")

        proposed = p4_diagnostics.get("proposed_claims", [])
        handles = p4_diagnostics.get("proposed_evidence_handle_per_claim", [])
        excerpts = p4_diagnostics.get("proposed_excerpt_per_claim", [])
        handle_results = p4_diagnostics.get("handle_validation_result_per_claim", [])
        excerpt_results = p4_diagnostics.get("excerpt_validation_result_per_claim", [])
        rejection_reasons = p4_diagnostics.get("deterministic_rejection_reason_per_claim", [])
        rendered = p4_diagnostics.get("rendered_final_claims", "")
        fallback_used = p4_diagnostics.get("fallback_used", False)
        fallback_reason = p4_diagnostics.get("fallback_reason")

    return {
        "knowledge_mode_active": knowledge_mode_active,
        "knowledge_terminal_output_transport": P5_KNOWLEDGE_TERMINAL_OUTPUT_TRANSPORT,
        "provider_response_format_attached": P5_PROVIDER_RESPONSE_FORMAT_ATTACHED,
        "tool_path_entered": tool_path_entered,
        "extractive_mode_deactivated_after_tool": tool_path_entered,
        "raw_terminal_content": raw_content,
        "json_parse_success": json_parse_success,
        "json_parse_failure_reason": json_parse_failure_reason,
        "schema_validation_result": schema_validation_result,
        "proposed_claims": proposed,
        "proposed_evidence_handle_per_claim": handles,
        "proposed_excerpt_per_claim": excerpts,
        "handle_validation_result_per_claim": handle_results,
        "excerpt_validation_result_per_claim": excerpt_results,
        "deterministic_rejection_reason_per_claim": rejection_reasons,
        "rendered_final_claims": rendered,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
    }


class P5TraceStore:
    """Write/read one sanitized P5 trace per agent run within its canonical run directory."""

    def __init__(
        self,
        run_directory: Path,
        run_id: str,
        *,
        secrets_to_hide: Iterable[str] = (),
    ) -> None:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("invalid canonical P5 run ID")
        if run_directory.is_symlink():
            raise ValueError("P5 trace run directory may not be a symlink")
        self.run_id = run_id
        self.run_directory = run_directory.resolve()
        if self.run_directory.name != run_id:
            raise ValueError("P5 trace directory must match canonical run ID")
        trace_directory = self.run_directory / "p5-traces"
        if trace_directory.is_symlink():
            raise ValueError("P5 trace directory may not be a symlink")
        trace_directory.mkdir(parents=True, exist_ok=True)
        self.trace_directory = trace_directory.resolve()
        if not self.trace_directory.is_relative_to(self.run_directory):
            raise ValueError("P5 trace path escapes canonical run directory")
        self._secrets_to_hide = tuple(secret for secret in secrets_to_hide if secret)

    def write(self, agent_run_id: UUID, diagnostics: Mapping[str, Any]) -> P5TraceArtifact:
        agent_id = _normalize_agent_run_id(agent_run_id)
        path = self._path_for(agent_id)
        if path.exists():
            raise FileExistsError("P5 trace already exists for agent run")
        clean_diagnostics = _validate_p5_diagnostics(diagnostics, self._secrets_to_hide)
        payload = {
            "schema_version": 1,
            "candidate": P5_TRACE_CANDIDATE_LABEL,
            "run_id": self.run_id,
            "agent_run_id": agent_id,
            "diagnostics": clean_diagnostics,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{agent_id}.", suffix=".tmp", dir=self.trace_directory
        )
        temporary_path = Path(temporary_name)
        created = False
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                raise FileExistsError("P5 trace already exists for agent run")
            os.link(temporary_path, path)
            created = True
            temporary_path.unlink()
            _fsync_directory(self.trace_directory)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            if created:
                path.unlink(missing_ok=True)
            raise
        return self.read(agent_run_id)

    def read(self, agent_run_id: UUID) -> P5TraceArtifact:
        agent_id = _normalize_agent_run_id(agent_run_id)
        path = self._path_for(agent_id)
        if not path.is_file():
            raise FileNotFoundError("P5 trace is missing for agent run")
        try:
            raw_bytes = path.read_bytes()
            payload = json.loads(raw_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("P5 trace sidecar is malformed") from None
        if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_FIELDS:
            raise ValueError("P5 trace sidecar has an invalid shape")
        if (
            not isinstance(payload.get("schema_version"), int)
            or isinstance(payload.get("schema_version"), bool)
            or payload.get("schema_version") != 1
            or payload.get("candidate") != P5_TRACE_CANDIDATE_LABEL
            or payload.get("run_id") != self.run_id
            or payload.get("agent_run_id") != agent_id
        ):
            raise ValueError("P5 trace sidecar identity does not match the requested run")
        diagnostics = payload.get("diagnostics")
        if not isinstance(diagnostics, dict):
            raise ValueError("P5 trace diagnostics are malformed")
        try:
            sanitized = _validate_p5_diagnostics(diagnostics, self._secrets_to_hide)
        except ValueError:
            raise ValueError("P5 trace diagnostics are malformed") from None
        if sanitized != diagnostics:
            raise ValueError("P5 trace sidecar contains unsanitized values")
        return P5TraceArtifact(
            path=path,
            relative_path=path.relative_to(self.run_directory).as_posix(),
            sha256=hashlib.sha256(raw_bytes).hexdigest(),
            payload=payload,
        )

    def _path_for(self, agent_run_id: str) -> Path:
        path = self.trace_directory / f"{agent_run_id}.json"
        if not path.resolve().is_relative_to(self.trace_directory):
            raise ValueError("P5 trace path escapes canonical run directory")
        return path


def verify_p5_trace_records(
    repo_root: Path,
    run_directory: Path,
    run_id: str,
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Verify P5 observation references against the exact per-agent sidecar set."""

    root = repo_root.resolve()
    if run_directory.is_symlink():
        raise ValueError("P5 trace run directory is invalid")
    run_path = run_directory.resolve()
    if run_path.name != run_id:
        raise ValueError("P5 trace run directory is invalid")
    canonical_root = (root / "evals/rag/v0.2/dev-evidence/canonical").resolve()
    try:
        run_path.relative_to(canonical_root)
    except ValueError as error:
        raise ValueError("P5 trace run directory escapes canonical evidence root") from error
    store = P5TraceStore(run_path, run_id)
    seen_agent_ids: set[str] = set()
    references: list[dict[str, str]] = []
    for record in records:
        agent_run_id = record.get("agent_run_id")
        if not isinstance(agent_run_id, str) or agent_run_id in seen_agent_ids:
            raise ValueError("P5 observations have a missing or duplicate agent run ID")
        seen_agent_ids.add(agent_run_id)
        expected = record.get("p5_trace_artifact")
        if not isinstance(expected, Mapping):
            raise ValueError("P5 observation is missing its trace artifact reference")
        artifact = store.read(UUID(agent_run_id))
        if (
            expected.get("path") != artifact.relative_path
            or expected.get("sha256") != artifact.sha256
        ):
            raise ValueError("P5 observation trace artifact reference does not match sidecar bytes")
        if record.get("p5_diagnostics") != artifact.payload["diagnostics"]:
            raise ValueError("P5 observation diagnostics do not match its trace sidecar")
        try:
            repository_path = artifact.path.resolve().relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("P5 trace artifact escapes repository root") from error
        references.append({"path": repository_path, "sha256": artifact.sha256})
    entries = list(store.trace_directory.iterdir())
    actual_sidecars = {path.stem for path in entries if path.suffix == ".json" and path.is_file()}
    if actual_sidecars != seen_agent_ids:
        raise ValueError("P5 trace sidecars do not exactly match checkpoint observations")
    expected_names = {f"{agent_id}.json" for agent_id in seen_agent_ids}
    if any(not path.is_file() or path.name not in expected_names for path in entries):
        raise ValueError("P5 trace directory contains unrecognized files")
    return references


def _validate_p5_diagnostics(
    diagnostics: Mapping[str, Any], secrets_to_hide: tuple[str, ...]
) -> dict[str, Any]:
    if not isinstance(diagnostics, Mapping) or set(diagnostics) != P5_TRACE_FIELDS:
        raise ValueError("P5 diagnostic field contract mismatch")
    if diagnostics["knowledge_terminal_output_transport"] != P5_KNOWLEDGE_TERMINAL_OUTPUT_TRANSPORT:
        raise ValueError("P5 transport does not match the frozen contract")
    if diagnostics["provider_response_format_attached"] is not False:
        raise ValueError("P5 response_format must remain unattached")
    active = diagnostics["knowledge_mode_active"]
    tool_entered = diagnostics["tool_path_entered"]
    deactivated = diagnostics["extractive_mode_deactivated_after_tool"]
    if not isinstance(active, bool) or not isinstance(tool_entered, bool):
        raise ValueError("P5 mode diagnostics are malformed")
    if (
        not isinstance(deactivated, bool)
        or deactivated is not tool_entered
        or (active and tool_entered)
    ):
        raise ValueError("P5 tool-mode diagnostics are inconsistent")

    raw = diagnostics["raw_terminal_content"]
    json_success = diagnostics["json_parse_success"]
    json_failure = diagnostics["json_parse_failure_reason"]
    schema_valid = diagnostics["schema_validation_result"]
    proposed = diagnostics["proposed_claims"]
    handles = diagnostics["proposed_evidence_handle_per_claim"]
    excerpts = diagnostics["proposed_excerpt_per_claim"]
    handle_results = diagnostics["handle_validation_result_per_claim"]
    excerpt_results = diagnostics["excerpt_validation_result_per_claim"]
    reasons = diagnostics["deterministic_rejection_reason_per_claim"]
    rendered = diagnostics["rendered_final_claims"]
    fallback = diagnostics["fallback_used"]
    fallback_reason = diagnostics["fallback_reason"]

    if not isinstance(rendered, str) or not isinstance(fallback, bool):
        raise ValueError("P5 response diagnostics are malformed")
    if fallback != (fallback_reason is not None):
        raise ValueError("P5 fallback diagnostics are inconsistent")
    if fallback_reason is not None and fallback_reason not in _P5_FALLBACK_REASONS:
        raise ValueError("P5 fallback reason is invalid")
    if not all(
        isinstance(items, list)
        for items in (proposed, handles, excerpts, handle_results, excerpt_results, reasons)
    ):
        raise ValueError("P5 per-claim diagnostics are malformed")
    if any(
        not isinstance(claim, dict)
        or set(claim) != _CLAIM_FIELDS
        or any(not isinstance(claim[key], str) for key in _CLAIM_FIELDS)
        for claim in proposed
    ):
        raise ValueError("P5 claim diagnostics are malformed")
    count = len(proposed)
    if any(
        len(items) != count
        for items in (handles, excerpts, handle_results, excerpt_results, reasons)
    ):
        raise ValueError("P5 per-claim diagnostic arrays are inconsistent")
    if handles != [claim["evidence_handle"] for claim in proposed] or excerpts != [
        claim["supporting_excerpt"] for claim in proposed
    ]:
        raise ValueError("P5 claim projections do not match proposed claims")
    if any(not isinstance(value, bool) for value in handle_results):
        raise ValueError("P5 handle validation results are malformed")
    if any(value is not None and not isinstance(value, bool) for value in excerpt_results):
        raise ValueError("P5 excerpt validation results are malformed")
    if any(value is not None and value not in _P5_REJECTION_REASONS for value in reasons):
        raise ValueError("P5 rejection reason is invalid")

    accepted: list[dict[str, str]] = []
    for index, claim in enumerate(proposed):
        claim_text = claim["claim_text"]
        excerpt = excerpts[index]
        expected = (
            "invalid_handle"
            if not handle_results[index]
            else "empty_excerpt"
            if not excerpt.strip()
            else "excerpt_mismatch"
            if excerpt_results[index] is not True
            else "empty_claim"
            if not claim_text.strip()
            else "claim_not_substring"
            if claim_text not in excerpt
            else None
        )
        if reasons[index] != expected:
            raise ValueError("P5 deterministic rejection reason disagrees with validation")
        if expected is None:
            accepted.append(claim)
    if rendered != "\n".join(
        f"{claim['claim_text']} [[{claim['evidence_handle']}]]" for claim in accepted
    ):
        raise ValueError("P5 rendered claims do not match accepted claims")

    response_fields = (raw, json_success, json_failure, schema_valid)
    if not active:
        if (
            any(value is not None for value in response_fields)
            or proposed
            or handles
            or excerpts
            or handle_results
            or excerpt_results
            or reasons
            or rendered
            or fallback
            or fallback_reason is not None
        ):
            raise ValueError("inactive P5 path must use not-applicable response values")
    else:
        if raw is not None and not isinstance(raw, str):
            raise ValueError("P5 raw terminal content is malformed")
        if not isinstance(json_success, bool):
            raise ValueError("P5 JSON parse result is malformed")
        if json_success:
            if json_failure is not None or not isinstance(schema_valid, bool):
                raise ValueError("P5 schema result is inconsistent with JSON parsing")
            if not schema_valid and (
                proposed or rendered or not fallback or fallback_reason != "invalid_p4_schema"
            ):
                raise ValueError("P5 schema-invalid response must fail closed")
        elif (
            json_failure not in {"invalid_json", "missing_or_blank_terminal_content"}
            or schema_valid is not None
            or proposed
            or rendered
            or not fallback
            or fallback_reason != json_failure
        ):
            raise ValueError("P5 malformed JSON response must fail closed")
        if (
            json_success
            and schema_valid
            and not accepted
            and (
                not fallback
                or fallback_reason
                not in {"all_claims_rejected", "citation_finalizer_rejected_claims"}
            )
        ):
            raise ValueError("P5 empty accepted claims must fail closed")

    return {key: _sanitize_value(value, secrets_to_hide) for key, value in diagnostics.items()}


def _normalize_agent_run_id(agent_run_id: UUID) -> str:
    try:
        normalized = str(UUID(str(agent_run_id)))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("invalid P5 agent run ID") from None
    if str(agent_run_id) != normalized:
        raise ValueError("invalid P5 agent run ID")
    return normalized


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "P5TraceArtifact",
    "P5TraceStore",
    "frozen_p5_observability_contract",
    "project_p5_diagnostics",
    "verify_p5_trace_records",
]
