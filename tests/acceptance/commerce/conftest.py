"""Black-box HTTP fixtures; this package intentionally has no service imports."""

import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest
from scripts.acceptance_time import parse_acceptance_as_of

MANIFEST_PATH = Path(__file__).parents[1] / "fixtures" / "novacommerce-scenarios.json"
ACCEPTANCE_ROOT = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.commerce_acceptance
    for item in items:
        try:
            item.path.relative_to(ACCEPTANCE_ROOT)
        except ValueError:
            continue
        item.add_marker(marker)


@pytest.fixture(scope="session")
def manifest() -> dict[str, object]:
    configured = os.environ.get("ACCEPTANCE_SCENARIO_MANIFEST")
    path = Path(configured) if configured else MANIFEST_PATH
    if not path.is_file():
        pytest.fail("ACCEPTANCE_SCENARIO_MANIFEST is required for black-box acceptance")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        pytest.fail("acceptance scenario manifest must be an object")
    return value


@pytest.fixture(scope="session")
def acceptance_as_of() -> datetime:
    configured = os.environ.get("ACCEPTANCE_AS_OF")
    if not configured:
        pytest.fail("ACCEPTANCE_AS_OF is required for black-box acceptance")
    try:
        return parse_acceptance_as_of(configured)
    except ValueError as error:
        pytest.fail(str(error))


@pytest.fixture(scope="session")
def base_url() -> str:
    value = os.environ.get("ACCEPTANCE_BASE_URL")
    if not value:
        pytest.fail("ACCEPTANCE_BASE_URL is required for black-box acceptance")
    return value.rstrip("/")


@pytest.fixture(scope="session")
def service_token() -> str:
    value = os.environ.get("ACCEPTANCE_SERVICE_TOKEN")
    if not value or len(value) < 32:
        pytest.fail("ACCEPTANCE_SERVICE_TOKEN must be configured and non-blank")
    return value


@pytest.fixture(scope="session")
def client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=15.0) as value:
        yield value


@pytest.fixture(scope="session")
def authenticated_headers(service_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {service_token}"}


@pytest.fixture(scope="session")
def primary_headers(
    authenticated_headers: dict[str, str], manifest: dict[str, object]
) -> dict[str, str]:
    scenario_ids = manifest["scenario_ids"]
    assert isinstance(scenario_ids, dict)
    customer_id = scenario_ids["customer_primary"]
    assert isinstance(customer_id, str)
    return {**authenticated_headers, "X-VerbaOps-Customer-ID": customer_id}


@pytest.fixture
def idempotency_key() -> str:
    return f"acceptance-{uuid4()}"


def scenario_id(manifest: dict[str, object], name: str) -> str:
    scenarios = manifest["scenario_ids"]
    if not isinstance(scenarios, dict) or not isinstance(scenarios.get(name), str):
        raise AssertionError(f"missing scenario {name}")
    return cast(str, scenarios[name])


def overlay_id(manifest: dict[str, object], name: str) -> str:
    overlays = manifest["overlay_ids"]
    if not isinstance(overlays, dict) or not isinstance(overlays.get(name), str):
        raise AssertionError(f"missing overlay {name}")
    return cast(str, overlays[name])
