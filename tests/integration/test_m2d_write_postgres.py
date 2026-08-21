"""Real PostgreSQL contract coverage for M2D transactional writes."""

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from os import environ
from typing import Any
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from novacommerce.api.app import create_app
from novacommerce.api.errors import APIError
from novacommerce.config.settings import DatabaseSettings, Environment, Settings
from novacommerce.db.models.commerce_event import CommerceEvent
from novacommerce.idempotency import (
    WriteOutcome,
    execute_idempotent_write,
    request_fingerprint,
)
from novacommerce.seed.config import SeedConfig
from novacommerce.seed.ids import scenario_uuid
from novacommerce.seed.service import seed_database

pytestmark = pytest.mark.integration

TOKEN = "m2d-integration-token-" + "x" * 32
TABLES = (
    "commerce_events",
    "idempotency_records",
    "support_tickets",
    "return_items",
    "returns",
    "refunds",
    "shipments",
    "order_items",
    "orders",
    "delivery_slots",
    "products",
    "customers",
)


@pytest.fixture(scope="module")
def database_url() -> str:
    url = environ.get("NOVACOMMERCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("NOVACOMMERCE_TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("M2D integration requires postgresql+asyncpg")
    return url


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    database_engine = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    yield database_engine
    await database_engine.dispose()


async def clear_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        for table in TABLES:
            await connection.execute(text(f"DELETE FROM {table}"))


@pytest_asyncio.fixture
async def live_app(database_url: str, engine: AsyncEngine) -> AsyncIterator[Any]:
    await clear_database(engine)
    settings = Settings(
        environment=Environment.TEST,
        database=DatabaseSettings(url=SecretStr(database_url)),
        service_token=SecretStr(TOKEN),
    )
    await seed_database(settings, SeedConfig())
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        yield app
    await clear_database(engine)


async def request(
    app: Any,
    method: str,
    path: str,
    *,
    customer_id: UUID | None = None,
    key: str | None = None,
    body: dict[str, Any] | None = None,
    token: str | None = TOKEN,
) -> httpx.Response:
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if customer_id is not None:
        headers["X-VerbaOps-Customer-ID"] = str(customer_id)
    if key is not None:
        headers["Idempotency-Key"] = key
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json=body)


async def counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as connection:
        return {
            table: int(
                (await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            )
            for table in TABLES
        }


async def order_item_id(engine: AsyncEngine, order_id: UUID) -> UUID:
    async with engine.connect() as connection:
        value = (
            await connection.execute(
                text("SELECT id FROM order_items WHERE order_id = :order_id ORDER BY id LIMIT 1"),
                {"order_id": order_id},
            )
        ).scalar_one()
    return UUID(str(value))


@pytest.mark.asyncio
async def test_m2d_postgres_transactional_writes_and_replay(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    standard_product = scenario_uuid(config, "product_standard_stock")
    cancellable = scenario_uuid(config, "order_cancellable")
    shipped = scenario_uuid(config, "order_already_shipped")
    other_order = scenario_uuid(config, "order_other_customer")
    delivered_29d = scenario_uuid(config, "order_delivered_29d")
    delivered_31d = scenario_uuid(config, "order_delivered_31d")
    refund_500 = scenario_uuid(config, "order_refund_500_00")
    refund_501 = scenario_uuid(config, "order_refund_501_00")
    available_slot = scenario_uuid(config, "slot_available")
    full_slot = scenario_uuid(config, "slot_full")

    before = await counts(engine)

    create_body = {"items": [{"product_id": str(standard_product), "quantity": 2}]}
    created = await request(
        live_app,
        "POST",
        "/v1/orders",
        customer_id=primary,
        key="m2d-create-order-001",
        body=create_body,
    )
    replay = await request(
        live_app,
        "POST",
        "/v1/orders",
        customer_id=primary,
        key="m2d-create-order-001",
        body=create_body,
    )
    assert created.status_code == 201
    assert replay.status_code == 201
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert replay.json() == created.json()
    created_order = UUID(created.json()["order"]["id"])
    assert Decimal(created.json()["order"]["total"]) == Decimal(
        created.json()["order"]["items"][0]["line_total"]
    )

    mismatch = await request(
        live_app,
        "POST",
        "/v1/orders",
        customer_id=primary,
        key="m2d-create-order-001",
        body={"items": [{"product_id": str(standard_product), "quantity": 1}]},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "idempotency_key_reused"

    cancelled = await request(
        live_app,
        "POST",
        f"/v1/orders/{cancellable}/cancel",
        customer_id=primary,
        key="m2d-cancel-001",
        body={},
    )
    cancelled_replay = await request(
        live_app,
        "POST",
        f"/v1/orders/{cancellable}/cancel",
        customer_id=primary,
        key="m2d-cancel-001",
        body={},
    )
    assert cancelled.status_code == cancelled_replay.status_code == 200
    assert cancelled.json()["order"]["status"] == "cancelled"
    assert cancelled_replay.headers["X-Idempotent-Replay"] == "true"
    already_cancelled = await request(
        live_app,
        "POST",
        f"/v1/orders/{cancellable}/cancel",
        customer_id=primary,
        key="m2d-cancel-002",
        body={},
    )
    assert already_cancelled.status_code == 409
    assert already_cancelled.json()["error"]["code"] == "order_not_cancellable"
    foreign_cancel = await request(
        live_app,
        "POST",
        f"/v1/orders/{other_order}/cancel",
        customer_id=primary,
        key="m2d-cross-customer-001",
        body={},
    )
    assert foreign_cancel.status_code == 404
    assert foreign_cancel.json()["error"]["code"] == "resource_not_found"

    rescheduled = await request(
        live_app,
        "POST",
        f"/v1/orders/{shipped}/reschedule",
        customer_id=primary,
        key="m2d-reschedule-001",
        body={"delivery_slot_id": str(available_slot)},
    )
    assert rescheduled.status_code == 200
    same_slot = await request(
        live_app,
        "POST",
        f"/v1/orders/{shipped}/reschedule",
        customer_id=primary,
        key="m2d-reschedule-002",
        body={"delivery_slot_id": str(available_slot)},
    )
    assert same_slot.status_code == 200
    assert same_slot.json()["delivery_slot_id"] == str(available_slot)

    async with engine.connect() as connection:
        candidate = (
            await connection.execute(
                text(
                    "SELECT o.id FROM orders o JOIN shipments s ON s.order_id = o.id "
                    "WHERE o.customer_id = :customer_id AND o.status = 'confirmed' "
                    "AND s.status = 'label_created' ORDER BY o.id LIMIT 1"
                ),
                {"customer_id": primary},
            )
        ).scalar_one()
    full = await request(
        live_app,
        "POST",
        f"/v1/orders/{candidate}/reschedule",
        customer_id=primary,
        key="m2d-full-slot-001",
        body={"delivery_slot_id": str(full_slot)},
    )
    full_replay = await request(
        live_app,
        "POST",
        f"/v1/orders/{candidate}/reschedule",
        customer_id=primary,
        key="m2d-full-slot-001",
        body={"delivery_slot_id": str(full_slot)},
    )
    assert full.status_code == full_replay.status_code == 409
    assert full.json() == full_replay.json()
    assert full_replay.headers["X-Idempotent-Replay"] == "true"
    assert full.json()["error"]["code"] == "delivery_slot_full"

    delivered_item = await order_item_id(engine, delivered_29d)
    return_body = {
        "order_id": str(delivered_29d),
        "reason": "M2D integration return",
        "items": [{"order_item_id": str(delivered_item), "quantity": 1}],
    }
    returned = await request(
        live_app,
        "POST",
        "/v1/returns",
        customer_id=primary,
        key="m2d-return-001",
        body=return_body,
    )
    returned_replay = await request(
        live_app,
        "POST",
        "/v1/returns",
        customer_id=primary,
        key="m2d-return-001",
        body=return_body,
    )
    assert returned.status_code == returned_replay.status_code == 201
    assert returned_replay.headers["X-Idempotent-Replay"] == "true"
    expired_item = await order_item_id(engine, delivered_31d)
    expired = await request(
        live_app,
        "POST",
        "/v1/returns",
        customer_id=primary,
        key="m2d-return-expired-001",
        body={
            "order_id": str(delivered_31d),
            "reason": "expired",
            "items": [{"order_item_id": str(expired_item), "quantity": 1}],
        },
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "return_window_expired"

    refund_500_response = await request(
        live_app,
        "POST",
        f"/v1/orders/{refund_500}/refunds",
        customer_id=primary,
        key="m2d-refund-500-001",
        body={"amount": "500.00", "reason": "threshold test"},
    )
    refund_501_response = await request(
        live_app,
        "POST",
        f"/v1/orders/{refund_501}/refunds",
        customer_id=primary,
        key="m2d-refund-501-001",
        body={"amount": "500.01", "reason": "manual threshold test"},
    )
    assert refund_500_response.status_code == refund_501_response.status_code == 201
    assert refund_500_response.json()["requires_manual_approval"] is False
    assert refund_501_response.json()["requires_manual_approval"] is True
    assert refund_501_response.json()["status"] == "pending_manual_approval"

    ticket = await request(
        live_app,
        "POST",
        "/v1/support-tickets",
        customer_id=primary,
        key="m2d-ticket-001",
        body={"subject": "Integration", "description": "Transactional ticket"},
    )
    ticket_replay = await request(
        live_app,
        "POST",
        "/v1/support-tickets",
        customer_id=primary,
        key="m2d-ticket-001",
        body={"subject": "Integration", "description": "Transactional ticket"},
    )
    assert ticket.status_code == ticket_replay.status_code == 201
    assert ticket.json()["order_id"] is None
    assert ticket_replay.headers["X-Idempotent-Replay"] == "true"

    missing_key = await request(
        live_app,
        "POST",
        "/v1/support-tickets",
        customer_id=primary,
        body={"subject": "No key", "description": "Must fail before transaction"},
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "idempotency_key_required"

    concurrent_body = {"items": [{"product_id": str(standard_product), "quantity": 1}]}
    concurrent = await asyncio.gather(
        request(
            live_app,
            "POST",
            "/v1/orders",
            customer_id=primary,
            key="m2d-concurrent-create-001",
            body=concurrent_body,
        ),
        request(
            live_app,
            "POST",
            "/v1/orders",
            customer_id=primary,
            key="m2d-concurrent-create-001",
            body=concurrent_body,
        ),
    )
    assert {response.status_code for response in concurrent} == {201}
    assert concurrent[0].json() == concurrent[1].json()

    after = await counts(engine)
    assert after["orders"] == before["orders"] + 2
    assert after["commerce_events"] > before["commerce_events"]
    assert after["idempotency_records"] > before["idempotency_records"]
    assert after["idempotency_records"] >= after["commerce_events"]

    async with engine.connect() as connection:
        order_status, product_stock = (
            await connection.execute(
                text(
                    "SELECT o.status, p.stock FROM orders o "
                    "JOIN order_items oi ON oi.order_id = o.id "
                    "JOIN products p ON p.id = oi.product_id WHERE o.id = :order_id"
                ),
                {"order_id": created_order},
            )
        ).one()
    assert order_status == "confirmed"
    assert product_stock >= 0


@pytest.mark.asyncio
async def test_m2d_postgres_seed_state_and_read_only_counters(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    before = await counts(engine)
    assert before["customers"] == 1000
    assert before["products"] == 2000
    assert before["orders"] == 10000
    assert before["order_items"] == 25000
    assert before["shipments"] == 9200
    assert before["delivery_slots"] == 180
    assert before["refunds"] == 800
    assert before["returns"] == 600
    assert before["return_items"] == 900
    assert before["support_tickets"] == 500
    assert before["idempotency_records"] == 0
    assert before["commerce_events"] == 0
    assert await counts(engine) == before


@pytest.mark.asyncio
async def test_m2d_operation_failure_rolls_back_event_and_idempotency(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    key = "m2d-injected-operation-failure"
    before = await counts(engine)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as session:

        async def operation(active: AsyncSession) -> WriteOutcome:
            active.add(
                CommerceEvent(
                    event_type="injected.failure",
                    aggregate_type="test",
                    aggregate_id=primary,
                    customer_id=primary,
                    idempotency_key=key,
                    payload={"injected": True},
                )
            )
            await active.flush()
            raise RuntimeError("injected failure after event")

        with pytest.raises(APIError) as error:
            await execute_idempotent_write(
                session,
                key=key,
                operation="test.failure",
                customer_id=primary,
                fingerprint=request_fingerprint("test.failure", primary, body={}),
                operation_fn=operation,
            )
        assert error.value.code == "write_outcome_unknown"
    assert await counts(engine) == before


@pytest.mark.asyncio
async def test_m2d_ambiguous_commit_replays_committed_outcome(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    key = "m2d-ambiguous-commit-test"
    fingerprint = request_fingerprint("test.commit", primary, body={"v": 1})
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    calls = 0

    async def operation(active: AsyncSession) -> WriteOutcome:
        nonlocal calls
        calls += 1
        return WriteOutcome(200, {"accepted": True})

    async with sessions() as session:

        async def commit_then_lose_ack() -> None:
            await session.commit()
            raise RuntimeError("injected acknowledgement loss")

        with pytest.raises(APIError) as error:
            await execute_idempotent_write(
                session,
                key=key,
                operation="test.commit",
                customer_id=primary,
                fingerprint=fingerprint,
                operation_fn=operation,
                commit_fn=commit_then_lose_ack,
            )
        assert error.value.code == "write_outcome_unknown"

    async with sessions() as retry_session:
        retry = await execute_idempotent_write(
            retry_session,
            key=key,
            operation="test.commit",
            customer_id=primary,
            fingerprint=fingerprint,
            operation_fn=operation,
        )
    assert retry.replayed is True
    assert retry.outcome.status_code == 200
    assert retry.outcome.body == {"accepted": True}
    assert calls == 1
