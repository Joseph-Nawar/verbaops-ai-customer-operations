"""Generate and check the normalized NovaCommerce /v1 OpenAPI contract."""

import argparse
import difflib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from novacommerce.api.app import create_app
from novacommerce.config.settings import Environment, Settings

_COSMETIC_KEYS = frozenset({"description", "summary", "examples"})
_COMPONENT_PREFIX = "#/components/"


def _without_cosmetic(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_cosmetic(item)
            for key, item in value.items()
            if key not in _COSMETIC_KEYS
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
    """Return a stable client-contract view of the application's OpenAPI document."""

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


def generate_normalized_openapi() -> bytes:
    """Generate the contract from the real FastAPI application without starting I/O."""

    settings = Settings(
        environment=Environment.TEST,
        service_token=SecretStr("m2e-contract-test-token-" + "x" * 32),
    )
    app = create_app(settings=settings)
    return normalized_bytes(app.openapi())


def _check(path: Path) -> int:
    expected = path.read_bytes() if path.exists() else b""
    actual = generate_normalized_openapi()
    if actual == expected:
        print(f"OpenAPI contract is up to date: {path}")
        return 0
    print(f"OpenAPI contract differs: {path}")
    diff = difflib.unified_diff(
        expected.decode("utf-8", errors="replace").splitlines(),
        actual.decode("utf-8").splitlines(),
        fromfile=str(path),
        tofile="generated",
        lineterm="",
    )
    print("\n".join(list(diff)[:120]))
    return 1


def _update(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(generate_normalized_openapi())
    print(f"Updated OpenAPI contract: {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--update", action="store_true")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    return _check(args.path) if args.check else _update(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
