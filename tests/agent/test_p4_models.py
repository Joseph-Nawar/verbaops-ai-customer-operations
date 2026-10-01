from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from verbaops.agent.p4_models import P4Response
from verbaops.llm.models import StructuredResponse

FROZEN_SCHEMA_PATH = (
    Path(__file__).parents[2] / "evals/rag/v0.2/scorer-v2/p4-output.schema.json"
)


def _canonical_schema(value: Any, root: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if reference is not None:
            prefix = "#/$defs/"
            assert reference.startswith(prefix)
            return _canonical_schema(root["$defs"][reference.removeprefix(prefix)], root)
        return {
            key: _canonical_schema(child, root)
            for key, child in value.items()
            if key not in {"$schema", "$id", "title", "description", "$defs", "definitions"}
        }
    if isinstance(value, list):
        return [_canonical_schema(child, root) for child in value]
    return value


def test_p4_response_requires_claims_and_all_three_claim_fields() -> None:
    claim = {
        "claim_text": "Returns are accepted within 30 days.",
        "evidence_handle": "K1",
        "supporting_excerpt": "Returns are accepted within 30 days.",
    }

    assert P4Response.model_validate({"claims": [claim]}).claims[0].claim_text == claim[
        "claim_text"
    ]
    assert P4Response.model_validate({"claims": []}).claims == []
    with pytest.raises(ValidationError):
        P4Response.model_validate({})
    with pytest.raises(ValidationError):
        P4Response.model_validate({"claims": [{"claim_text": "x", "evidence_handle": "K1"}]})


@pytest.mark.parametrize(
    "claim",
    [
        {"claim_text": "", "evidence_handle": "K1", "supporting_excerpt": "x"},
        {"claim_text": "x", "evidence_handle": "", "supporting_excerpt": "x"},
        {"claim_text": "x", "evidence_handle": "K1", "supporting_excerpt": ""},
    ],
)
def test_p4_claim_strings_must_meet_frozen_minimum_length(claim: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        P4Response.model_validate({"claims": [claim]})


def test_p4_response_rejects_extra_fields_at_both_levels() -> None:
    claim = {
        "claim_text": "x",
        "evidence_handle": "K1",
        "supporting_excerpt": "x",
        "citation": "K1",
    }
    with pytest.raises(ValidationError):
        P4Response.model_validate({"claims": [claim]})
    with pytest.raises(ValidationError):
        P4Response.model_validate({"claims": [], "answer": "x"})


def test_generated_strict_schema_matches_entire_frozen_p4_contract() -> None:
    frozen = json.loads(FROZEN_SCHEMA_PATH.read_text(encoding="utf-8"))
    generated_format = StructuredResponse.response_format(P4Response)
    generated = generated_format["json_schema"]["schema"]

    assert _canonical_schema(generated, generated) == _canonical_schema(frozen, frozen)
