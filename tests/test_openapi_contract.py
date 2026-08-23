"""Tests for deterministic NovaCommerce OpenAPI contract normalization."""

import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts.normalize_openapi import normalize_openapi, normalized_bytes
from scripts.openapi_contract import normalize_openapi as pure_normalize_openapi
from scripts.openapi_contract import normalized_bytes as pure_normalized_bytes

ROOT = Path(__file__).parents[1]


def document() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "NovaCommerce", "version": "1", "description": "noise"},
        "paths": {
            "/health": {"get": {"responses": {"200": {"description": "health"}}}},
            "/v1/products/search": {
                "get": {
                    "summary": "noise",
                    "description": "noise",
                    "security": [{"BearerAuth": []}],
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "minLength": 1},
                            "description": "noise",
                            "examples": {"sample": {"value": "x"}},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "noise",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Result"}
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            },
            "schemas": {
                "Result": {
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"$ref": "#/components/schemas/Nested"}},
                },
                "Nested": {"type": "string"},
                "Unused": {"type": "integer"},
            },
        },
    }


def test_normalization_is_deterministic_and_closes_references() -> None:
    first = normalized_bytes(document())
    second = normalized_bytes(deepcopy(document()))

    assert first == second
    normalized = normalize_openapi(document())
    assert set(normalized["paths"]) == {"/v1/products/search"}
    assert set(normalized["components"]["schemas"]) == {"Result", "Nested"}
    assert set(normalized["components"]["securitySchemes"]) == {"BearerAuth"}
    assert "description" not in normalized["paths"]["/v1/products/search"]["get"]
    assert "examples" not in normalized["paths"]["/v1/products/search"]["get"]["parameters"][0]


def test_normalization_strips_cosmetic_description_but_preserves_property_name() -> None:
    changed = deepcopy(document())
    changed["components"]["schemas"]["Result"]["description"] = "schema prose"
    changed["components"]["schemas"]["Result"]["properties"]["description"] = {
        "type": "string",
        "maxLength": 5000,
        "description": "property prose",
    }

    normalized = normalize_openapi(changed)
    result = normalized["components"]["schemas"]["Result"]

    assert "description" not in result
    assert result["properties"]["description"] == {
        "type": "string",
        "maxLength": 5000,
    }


def test_cosmetic_metadata_does_not_change_contract() -> None:
    changed = deepcopy(document())
    changed["paths"]["/v1/products/search"]["get"]["summary"] = "different"
    changed["paths"]["/v1/products/search"]["get"]["description"] = "different"
    changed["paths"]["/v1/products/search"]["get"]["parameters"][0]["examples"] = {}

    assert normalized_bytes(changed) == normalized_bytes(document())


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        (
            "path",
            lambda d: d["paths"].__setitem__("/v1/other", d["paths"].pop("/v1/products/search")),
        ),
        (
            "method",
            lambda d: d["paths"]["/v1/products/search"].__setitem__(
                "post", d["paths"]["/v1/products/search"].pop("get")
            ),
        ),
        (
            "security",
            lambda d: d["paths"]["/v1/products/search"]["get"].__setitem__("security", []),
        ),
        (
            "parameter required",
            lambda d: d["paths"]["/v1/products/search"]["get"]["parameters"][0].__setitem__(
                "required", False
            ),
        ),
        (
            "request body",
            lambda d: d["paths"]["/v1/products/search"]["get"].__setitem__(
                "requestBody", {"required": True}
            ),
        ),
        (
            "response",
            lambda d: d["paths"]["/v1/products/search"]["get"]["responses"].__setitem__("201", {}),
        ),
        (
            "component",
            lambda d: d["components"]["schemas"]["Nested"].__setitem__("type", "integer"),
        ),
        (
            "component required",
            lambda d: d["components"]["schemas"]["Result"]["required"].append("extra"),
        ),
    ],
)
def test_contract_semantic_drift_changes_bytes(label: str, mutate: Any) -> None:
    changed = deepcopy(document())
    mutate(changed)
    assert normalized_bytes(changed) != normalized_bytes(document()), label


def test_stale_snapshot_is_detectable_without_mutating_expected_bytes() -> None:
    expected = normalized_bytes(document())
    changed = deepcopy(document())
    changed["paths"]["/v1/products/search"]["get"]["security"] = []

    assert normalized_bytes(changed) != expected
    assert expected == normalized_bytes(document())


def test_pure_contract_module_matches_backward_compatible_exports() -> None:
    assert pure_normalize_openapi(document()) == normalize_openapi(document())
    assert pure_normalized_bytes(document()) == normalized_bytes(document())


def test_normalize_script_runs_by_file_path_for_make_contract_check() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "normalize_openapi.py"),
            "--check",
            str(ROOT / "contracts" / "novacommerce-openapi.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
