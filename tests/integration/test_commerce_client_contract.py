"""Permanent real NovaCommerce contract tests through the application client."""

import json
import os
from collections.abc import AsyncIterator
from datetime import date, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from scripts.acceptance_time import parse_acceptance_as_of

from verbaops.commerce import (
    CommerceAuthenticationError,
    CommerceClient,
    CommerceNotFoundError,
)
from verbaops.config import CommerceSettings

MANIFEST_PATH = (
    Path(__file__).parents[1] / "acceptance" / "fixtures" / "novacommerce-scenarios.json"
)


@pytest_asyncio.fixture(autouse=True)
async def isolate_commerce_test_state() -> AsyncIterator[None]:
    """Keep this HTTP-only contract outside the sibling PostgreSQL fixture."""

    yield


@pytest.fixture(scope="session")
def contract_manifest() -> dict[str, object]:
    configured = os.environ.get("ACCEPTANCE_SCENARIO_MANIFEST")
    path = Path(configured) if configured else MANIFEST_PATH
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


@pytest.fixture(scope="session")
def contract_base_url() -> str:
    return os.environ["ACCEPTANCE_BASE_URL"].rstrip("/")


@pytest.fixture(scope="session")
def contract_token() -> str:
    return os.environ["ACCEPTANCE_SERVICE_TOKEN"]


@pytest.fixture(scope="session")
def contract_as_of() -> date:
    return parse_acceptance_as_of(os.environ["ACCEPTANCE_AS_OF"]).date()


@pytest_asyncio.fixture
async def commerce_client(
    contract_base_url: str,
    contract_token: str,
) -> AsyncIterator[tuple[CommerceClient, list[httpx.Request]]]:
    requests: list[httpx.Request] = []

    async def record_request(request: httpx.Request) -> None:
        requests.append(request)

    settings = CommerceSettings(
        base_url=contract_base_url,
        service_token=SecretStr(contract_token),
    )
    async with httpx.AsyncClient(event_hooks={"request": [record_request]}) as http_client:
        yield CommerceClient(settings, http_client), requests


def scenario_id(manifest: dict[str, object], name: str) -> UUID:
    scenarios = manifest["scenario_ids"]
    assert isinstance(scenarios, dict)
    value = scenarios[name]
    assert isinstance(value, str)
    return UUID(value)


@pytest.mark.commerce_client_contract
@pytest.mark.asyncio
async def test_all_five_read_methods_use_real_commerce_and_get_only(
    commerce_client: tuple[CommerceClient, list[httpx.Request]],
    contract_manifest: dict[str, object],
    contract_as_of: date,
) -> None:
    client, requests = commerce_client
    customer_id = scenario_id(contract_manifest, "customer_primary")
    order_id = scenario_id(contract_manifest, "order_cancellable")

    order = await client.get_order(order_id, customer_id)
    shipment = await client.get_shipment(order_id, customer_id)
    refunds = await client.get_refunds(order_id, customer_id)
    products = await client.search_products("ACCEPTANCE-OVERLAY", 1)
    slots = await client.list_delivery_slots(
        contract_as_of + timedelta(days=39),
        contract_as_of + timedelta(days=42),
        True,
    )

    assert order.id == order_id
    assert order.customer_id == customer_id
    assert shipment.order_id == order_id
    assert refunds == []
    assert products.items
    assert products.limit == 1
    assert slots
    assert {request.method for request in requests} == {"GET"}
    assert len(requests) == 5
    assert all(
        request.headers["authorization"] == f"Bearer {os.environ['ACCEPTANCE_SERVICE_TOKEN']}"
        for request in requests
    )


@pytest.mark.commerce_client_contract
@pytest.mark.asyncio
async def test_customer_scoped_foreign_and_missing_orders_are_same_not_found(
    commerce_client: tuple[CommerceClient, list[httpx.Request]],
    contract_manifest: dict[str, object],
) -> None:
    client, _requests = commerce_client
    primary_customer = scenario_id(contract_manifest, "customer_primary")
    foreign_order = scenario_id(contract_manifest, "order_other_customer")

    with pytest.raises(CommerceNotFoundError) as foreign_error:
        await client.get_order(foreign_order, primary_customer)
    with pytest.raises(CommerceNotFoundError) as missing_error:
        await client.get_order(uuid4(), primary_customer)

    assert str(foreign_error.value) == str(missing_error.value)


@pytest.mark.commerce_client_contract
@pytest.mark.asyncio
async def test_invalid_service_token_is_normalized_without_secret_leak(
    contract_base_url: str,
    contract_token: str,
    contract_manifest: dict[str, object],
) -> None:
    invalid_token = f"invalid-{contract_token}"
    settings = CommerceSettings(
        base_url=contract_base_url,
        service_token=SecretStr(invalid_token),
    )
    customer_id = scenario_id(contract_manifest, "customer_primary")
    async with httpx.AsyncClient() as http_client:
        with pytest.raises(CommerceAuthenticationError) as error:
            await CommerceClient(settings, http_client).get_order(uuid4(), customer_id)

    assert invalid_token not in repr(error.value)
    assert invalid_token not in str(error.value)


@pytest.mark.commerce_client_contract
@pytest.mark.asyncio
async def test_injected_async_client_is_reused_for_sequential_calls(
    contract_base_url: str,
    contract_token: str,
    contract_manifest: dict[str, object],
) -> None:
    settings = CommerceSettings(
        base_url=contract_base_url,
        service_token=SecretStr(contract_token),
    )
    customer_id = scenario_id(contract_manifest, "customer_primary")
    order_id = scenario_id(contract_manifest, "order_cancellable")
    async with httpx.AsyncClient() as http_client:
        client = CommerceClient(settings, http_client)
        await client.get_order(order_id, customer_id)
        await client.get_shipment(order_id, customer_id)
        assert client._http_client is http_client
