"""Static M3C package-boundary and model-schema isolation tests."""

import ast
from pathlib import Path

from verbaops.tools.registry import build_commerce_read_registry


def test_verbaops_source_does_not_import_novacommerce() -> None:
    modules: set[str] = set()
    for path in Path("src/verbaops").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.add(node.module)

    assert not any(
        module == "novacommerce" or module.startswith("novacommerce.") for module in modules
    )


def test_production_registry_has_no_customer_or_write_surface() -> None:
    forbidden_fields = {"tenant_id", "principal_id", "customer_id", "roles", "service_token"}
    for definition in build_commerce_read_registry():
        assert set(definition.input_model.model_fields).isdisjoint(forbidden_fields)
        assert definition.risk_level.value == "read_only"
