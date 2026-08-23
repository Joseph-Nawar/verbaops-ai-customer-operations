"""Pure NovaCommerce OpenAPI contract normalization helpers."""

import json
from collections.abc import Mapping
from typing import Any

_COSMETIC_KEYS = frozenset({"description", "summary", "examples"})
_COMPONENT_PREFIX = "#/components/"


def _without_cosmetic(value: Any, *, mapping_role: str | None = None) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_cosmetic(
                item, mapping_role="properties" if key == "properties" else None
            )
            for key, item in value.items()
            if mapping_role == "properties" or key not in _COSMETIC_KEYS
        }
    if isinstance(value, list):
        return [_without_cosmetic(item) for item in value]
    return value


def _references(value: Any) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith(_COMPONENT_PREFIX):
            remainder = reference[len(_COMPONENT_PREFIX) :]
            section, separator, name = remainder.partition("/")
            if separator and section and name:
                found.add((section, name))
        for item in value.values():
            found.update(_references(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_references(item))
    return found


def _security_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, Mapping):
        security = value.get("security")
        if isinstance(security, list):
            for requirement in security:
                if isinstance(requirement, Mapping):
                    names.update(str(name) for name in requirement)
        for item in value.values():
            names.update(_security_names(item))
    elif isinstance(value, list):
        for item in value:
            names.update(_security_names(item))
    return names


def collect_references(
    document: Mapping[str, Any], paths: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Collect recursively reachable component definitions for selected paths."""

    components = document.get("components", {})
    if not isinstance(components, Mapping):
        return {}

    pending = _references(paths)
    pending.update(("securitySchemes", name) for name in _security_names(paths))
    collected: dict[str, dict[str, Any]] = {}
    while pending:
        section, name = pending.pop()
        section_values = components.get(section)
        if not isinstance(section_values, Mapping) or name not in section_values:
            continue
        if name in collected.setdefault(section, {}):
            continue
        definition = section_values[name]
        collected[section][name] = _without_cosmetic(definition)
        pending.update(_references(definition))
    return collected


def normalize_openapi(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable client-contract view of an OpenAPI document."""

    paths = document.get("paths", {})
    selected_paths = {
        path: _without_cosmetic(path_item)
        for path, path_item in paths.items()
        if isinstance(path, str) and path.startswith("/v1")
    }
    normalized = {
        str(key): _without_cosmetic(value)
        for key, value in document.items()
        if key not in {"paths", "components", "tags"}
    }
    normalized["paths"] = selected_paths
    components = collect_references(document, selected_paths)
    if components:
        normalized["components"] = components
    return normalized


def normalized_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize a normalized document deterministically."""

    return (
        json.dumps(normalize_openapi(document), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
