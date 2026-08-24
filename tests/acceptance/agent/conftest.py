"""Black-box fixtures for the complete M3E backend journey."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import httpx
import pytest

ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "fixtures" / "novacommerce-scenarios.json"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.agent_acceptance
    for item in items:
        try:
            item.path.relative_to(Path(__file__).parent)
        except ValueError:
            continue
        item.add_marker(marker)


@pytest.fixture(scope="session")
def manifest() -> dict[str, object]:
    configured = os.environ.get("AGENT_ACCEPTANCE_SCENARIO_MANIFEST")
    path = Path(configured) if configured else MANIFEST_PATH
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        pytest.fail("agent acceptance scenario manifest must be an object")
    return value


@pytest.fixture(scope="session")
def base_url() -> str:
    value = os.environ.get("AGENT_ACCEPTANCE_BASE_URL")
    if not value:
        pytest.fail("AGENT_ACCEPTANCE_BASE_URL is required")
    return value.rstrip("/")


@pytest.fixture(scope="session")
def bearer_token() -> str:
    value = os.environ.get("AGENT_ACCEPTANCE_TOKEN")
    if not value or len(value) < 32:
        pytest.fail("AGENT_ACCEPTANCE_TOKEN must be configured and non-blank")
    return value


@pytest.fixture(scope="session")
def client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=30.0) as value:
        yield value


@pytest.fixture(scope="session")
def authenticated_headers(bearer_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {bearer_token}"}


def scenario_id(manifest: dict[str, object], name: str) -> str:
    scenarios = manifest.get("scenario_ids")
    if not isinstance(scenarios, dict) or not isinstance(scenarios.get(name), str):
        raise AssertionError(f"missing scenario {name}")
    return cast(str, scenarios[name])
