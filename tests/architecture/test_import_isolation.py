"""Static package-boundary tests for the two service packages."""

import ast
from pathlib import Path


def imported_modules(package_root: Path) -> set[str]:
    modules: set[str] = set()
    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.add(node.module)
    return modules


def test_verbaops_source_does_not_import_novacommerce() -> None:
    modules = imported_modules(Path("src/verbaops"))
    assert not any(
        module == "novacommerce" or module.startswith("novacommerce.") for module in modules
    )


def test_novacommerce_source_does_not_import_verbaops() -> None:
    modules = imported_modules(Path("src/novacommerce"))
    assert not any(module == "verbaops" or module.startswith("verbaops.") for module in modules)
