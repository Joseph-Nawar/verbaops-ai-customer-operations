"""Architecture contracts for the provider-neutral Stage 7 worker boundary."""

import ast
from pathlib import Path

WORKER_MODULES = (
    Path("src/verbaops/voice/worker.py"),
    Path("src/verbaops/voice/worker_protocols.py"),
)
FORBIDDEN_IMPORTS = {
    "verbaops.actions.executor",
    "verbaops.actions.policy",
    "verbaops.commerce.client",
    "novacommerce",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            values.add(node.module)
    return values


def test_worker_modules_exist_without_direct_commerce_or_executor_imports() -> None:
    for path in WORKER_MODULES:
        imports = _imports(path)
        assert not imports & FORBIDDEN_IMPORTS
        source = path.read_text(encoding="utf-8")
        assert "CommerceClient" not in source
        assert "ActionExecutor" not in source
        assert "evaluate_action_policy" not in source
