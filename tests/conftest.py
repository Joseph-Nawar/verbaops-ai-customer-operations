"""Repository-wide pytest collection checks."""

from typing import Any

import pytest
from scripts.postgres_taxonomy import validate_postgres_classification


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    del config
    errors: list[str] = []
    for item in items:
        markers = {mark.name for mark in item.iter_markers()}
        try:
            validate_postgres_classification(item.nodeid, markers)
        except ValueError as error:
            errors.append(str(error))
    if errors:
        raise pytest.UsageError("PostgreSQL marker classification failed:\n" + "\n".join(errors))
