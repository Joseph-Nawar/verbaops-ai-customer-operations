"""Manifest loading and deterministic validation for the golden corpus."""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from verbaops.evaluation.models import APPROVED_CATEGORIES, APPROVED_TOOLS, EvaluationCase
from verbaops.tools.registry import build_commerce_read_registry


class CorpusAuditError(ValueError):
    """Raised when the versioned corpus violates an evaluation contract."""


class CorpusManifest(BaseModel):
    """Strict manifest containing the corpus-level expected invariants."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=2)
    expected_case_count: int = Field(ge=0)
    split_counts: dict[str, int]
    category_counts: dict[str, int]
    approved_tools: tuple[str, ...]
    scenario_manifest: str = Field(min_length=1)


class CorpusAudit(BaseModel):
    """Stable audit evidence returned for a valid corpus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_count: int = Field(ge=0)
    split_counts: dict[str, int]
    category_counts: dict[str, int]
    case_ids: tuple[str, ...]
    normalized_prompt_keys: tuple[str, ...]


def load_manifest(path: Path) -> CorpusManifest:
    """Load one strict JSON manifest."""

    try:
        return CorpusManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise CorpusAuditError(f"manifest could not be loaded: {error}") from error


def _normalized_prompt_key(case: EvaluationCase) -> str:
    context = "\n".join(f"{turn.role}:{turn.content}" for turn in case.conversation)
    normalized = unicodedata.normalize("NFKC", context)
    return " ".join(normalized.casefold().split())


def _scenario_values(manifest: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for value in manifest.values():
        if isinstance(value, Mapping):
            values.update(_scenario_values(value))
        elif isinstance(value, str):
            values.add(value)
    return values


def _validate_expected_arguments(case: EvaluationCase, errors: list[str]) -> None:
    if case.expected_tool is None:
        if case.expected_arguments:
            errors.append(f"{case.case_id}: no-tool case has nonempty expected arguments")
        if case.category not in {
            "benign-no-tool",
            "missing-ambiguous-identifiers",
            "unsupported-write",
            "safety-injection-identity-cross-customer",
        }:
            errors.append(f"{case.case_id}: no-tool case has an invalid category")
        return

    if case.expected_tool not in APPROVED_TOOLS:
        errors.append(f"{case.case_id}: unknown tool {case.expected_tool}")
        return
    identity_fields = {"customer_id", "tenant_id", "principal_id", "roles", "service_token"}
    forbidden = identity_fields.intersection(case.expected_arguments)
    if forbidden:
        errors.append(
            f"{case.case_id}: identity field used in expected arguments: {sorted(forbidden)}"
        )
        return

    definition = build_commerce_read_registry().get(case.expected_tool)
    fields = definition.input_model.model_fields
    unknown = set(case.expected_arguments).difference(fields)
    if unknown:
        errors.append(
            f"{case.case_id}: invalid arguments for {case.expected_tool}: {sorted(unknown)}"
        )
        return
    for field_name, value in case.expected_arguments.items():
        annotation = fields[field_name].annotation
        try:
            TypeAdapter(annotation).validate_python(value)
        except ValidationError as error:
            errors.append(f"{case.case_id}: invalid arguments for {case.expected_tool}: {error}")


def audit_corpus(
    manifest: CorpusManifest,
    cases: Sequence[EvaluationCase],
    scenario_manifest: Mapping[str, Any],
) -> CorpusAudit:
    """Validate all corpus invariants and return deterministic audit evidence."""

    errors: list[str] = []
    if manifest.dataset_version != "text-agent-v0.1":
        errors.append(f"dataset_version must be text-agent-v0.1, got {manifest.dataset_version}")
    if manifest.language != "en":
        errors.append(f"language must be en, got {manifest.language}")
    if tuple(manifest.approved_tools) != APPROVED_TOOLS:
        errors.append("approved tools do not match the exact Stage 3 registry")
    if len(cases) != manifest.expected_case_count:
        errors.append(f"case count expected {manifest.expected_case_count}, got {len(cases)}")

    case_ids = [case.case_id for case in cases]
    duplicate_ids = sorted(case_id for case_id, count in Counter(case_ids).items() if count > 1)
    if duplicate_ids:
        errors.append(f"duplicate case IDs: {duplicate_ids}")

    prompt_keys = [_normalized_prompt_key(case) for case in cases]
    duplicate_prompts = sorted(key for key, count in Counter(prompt_keys).items() if count > 1)
    if duplicate_prompts:
        errors.append(f"duplicate prompt keys: {duplicate_prompts}")

    split_counts: dict[str, int] = dict(Counter(str(case.split) for case in cases))
    for split, expected in manifest.split_counts.items():
        if split_counts.get(split, 0) != expected:
            errors.append(
                f"split count {split} expected {expected}, got {split_counts.get(split, 0)}"
            )
    category_counts: dict[str, int] = dict(Counter(case.category for case in cases))
    if set(manifest.category_counts) != set(APPROVED_CATEGORIES):
        errors.append("manifest category set does not match approved categories")
    for category in APPROVED_CATEGORIES:
        expected = manifest.category_counts.get(category, 0)
        if category_counts.get(category, 0) != expected:
            errors.append(
                f"category count {category} expected {expected}, got {category_counts.get(category, 0)}"
            )

    known_scenarios = _scenario_values(scenario_manifest)
    for case in cases:
        if case.dataset_version != manifest.dataset_version:
            errors.append(f"{case.case_id}: dataset_version mismatch")
        if case.language != manifest.language:
            errors.append(f"{case.case_id}: language mismatch")
        if case.category not in APPROVED_CATEGORIES:
            errors.append(f"{case.case_id}: unknown category {case.category}")
        if case.requires_confirmation:
            errors.append(f"{case.case_id}: requires_confirmation must be false")
        if case.customer_id is not None and str(case.customer_id) not in known_scenarios:
            errors.append(f"{case.case_id}: customer UUID is not canonical")
        for scenario_id in case.scenario_ids:
            try:
                scenario_text = str(UUID(str(scenario_id)))
            except (ValueError, TypeError):
                errors.append(f"{case.case_id}: malformed scenario reference {scenario_id}")
                continue
            if scenario_text not in known_scenarios:
                errors.append(f"{case.case_id}: scenario reference does not exist: {scenario_text}")
        _validate_expected_arguments(case, errors)
        if (
            case.expected_tool is None
            and case.expected_outcome.kind != "clarify"
            and case.category
            not in {
                "benign-no-tool",
                "unsupported-write",
                "safety-injection-identity-cross-customer",
                "missing-ambiguous-identifiers",
            }
        ):
            errors.append(f"{case.case_id}: expected tool is null without clarification outcome")

    if errors:
        raise CorpusAuditError("; ".join(errors))
    return CorpusAudit(
        case_count=len(cases),
        split_counts={split: split_counts.get(split, 0) for split in manifest.split_counts},
        category_counts={
            category: category_counts.get(category, 0) for category in APPROVED_CATEGORIES
        },
        case_ids=tuple(case_ids),
        normalized_prompt_keys=tuple(prompt_keys),
    )
