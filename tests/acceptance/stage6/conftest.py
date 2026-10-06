"""HTTP and durable-trace fixtures for the provider-free Stage 6 acceptance stack."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).parents[3]
MANIFEST_PATH = ROOT / "tests" / "acceptance" / "fixtures" / "novacommerce-scenarios.json"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "stage6_acceptance: provider-free black-box Stage 6 acceptance"
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.stage6_acceptance
    for item in items:
        try:
            item.path.relative_to(Path(__file__).parent)
        except ValueError:
            continue
        item.add_marker(marker)


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is required for Stage 6 acceptance")
    return value


@pytest.fixture(scope="session")
def manifest() -> dict[str, object]:
    configured = os.environ.get("STAGE6_ACCEPTANCE_SCENARIO_MANIFEST")
    path = Path(configured) if configured else MANIFEST_PATH
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        pytest.fail("Stage 6 acceptance scenario manifest must be an object")
    return value


@pytest.fixture(scope="session")
def base_url() -> str:
    return _required("STAGE6_ACCEPTANCE_BASE_URL").rstrip("/")


@pytest.fixture(scope="session")
def commerce_base_url() -> str:
    return _required("STAGE6_ACCEPTANCE_COMMERCE_BASE_URL").rstrip("/")


@pytest.fixture(scope="session")
def customer_token() -> str:
    return _required("STAGE6_ACCEPTANCE_CUSTOMER_TOKEN")


@pytest.fixture(scope="session")
def supervisor_token() -> str:
    return _required("STAGE6_ACCEPTANCE_SUPERVISOR_TOKEN")


@pytest.fixture(scope="session")
def other_customer_token() -> str:
    return _required("STAGE6_ACCEPTANCE_OTHER_CUSTOMER_TOKEN")


@pytest.fixture(scope="session")
def database_url() -> str:
    return _required("STAGE6_ACCEPTANCE_DATABASE_URL")


@pytest.fixture(scope="session")
def commerce_token() -> str:
    return _required("STAGE6_ACCEPTANCE_COMMERCE_TOKEN")


@pytest.fixture(scope="session")
def client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=30.0) as value:
        yield value


@pytest.fixture(scope="session")
def commerce_client(commerce_base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=commerce_base_url, timeout=30.0) as value:
        yield value


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def commerce_headers(token: str, customer_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-VerbaOps-Customer-ID": customer_id,
    }


def scenario_id(manifest: dict[str, object], name: str) -> str:
    scenarios = manifest.get("scenario_ids")
    if not isinstance(scenarios, dict) or not isinstance(scenarios.get(name), str):
        raise AssertionError(f"missing scenario {name}")
    return cast(str, scenarios[name])


def overlay_id(manifest: dict[str, object], name: str) -> str:
    overlays = manifest.get("overlay_ids")
    if not isinstance(overlays, dict) or not isinstance(overlays.get(name), str):
        raise AssertionError(f"missing overlay {name}")
    return cast(str, overlays[name])


def create_conversation(client: httpx.Client, token: str) -> UUID:
    response = client.post("/v1/conversations", headers=headers(token), json={})
    assert response.status_code == 201, response.text
    return UUID(response.json()["conversation_id"])


def propose(
    client: httpx.Client,
    token: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    conversation_id = create_conversation(client, token)
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=headers(token),
        json={
            "content": "stage6-propose:"
            + json.dumps(
                {"tool": tool_name, "arguments": arguments},
                separators=(",", ":"),
            )
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    action_requests = payload["action_requests"]
    assert len(action_requests) == 1, payload
    action_summary = action_requests[0]
    action_id = UUID(action_summary["action_request_id"])
    view = client.get(f"/v1/action-requests/{action_id}", headers=headers(token))
    assert view.status_code == 200, view.text
    return conversation_id, action_summary, view.json()


def durable_action(database_url: str, action_id: UUID) -> dict[str, Any]:
    async def read() -> dict[str, Any]:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                action = (
                    (
                        await connection.execute(
                            text(
                                "SELECT id, state, proposal_fingerprint, idempotency_key, "
                                "commerce_resource_id, verification_status, execution_attempt_count "
                                "FROM action_requests WHERE id = :id"
                            ),
                            {"id": action_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                events = (
                    (
                        await connection.execute(
                            text(
                                "SELECT sequence, event_type, previous_state, next_state "
                                "FROM action_events WHERE action_request_id = :id ORDER BY sequence"
                            ),
                            {"id": action_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                return {"action": dict(action), "events": [dict(event) for event in events]}
        finally:
            await engine.dispose()

    return asyncio.run(read())


def tool_trace(database_url: str, conversation_id: UUID) -> list[dict[str, Any]]:
    async def read() -> list[dict[str, Any]]:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                rows = (
                    (
                        await connection.execute(
                            text(
                                "SELECT ti.tool_name, ti.risk_level, ti.status, ti.result_json "
                                "FROM tool_invocations ti JOIN agent_runs ar "
                                "ON ar.id = ti.agent_run_id WHERE ar.conversation_id = :id "
                                "ORDER BY ti.sequence"
                            ),
                            {"id": conversation_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                return [dict(row) for row in rows]
        finally:
            await engine.dispose()

    return asyncio.run(read())
