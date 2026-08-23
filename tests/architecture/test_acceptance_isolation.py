"""Acceptance tests must remain black-box and dependency-isolated."""

import ast
from pathlib import Path

FORBIDDEN_ROOTS = {"novacommerce", "verbaops", "sqlalchemy", "asyncpg", "alembic"}


def test_commerce_acceptance_has_no_production_or_database_imports() -> None:
    root = Path(__file__).parents[1] / "acceptance" / "commerce"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module.split(".", 1)[0]] if node.module else []
            else:
                continue
            assert FORBIDDEN_ROOTS.isdisjoint(names), f"forbidden import in {path}: {names}"
