"""Real PostgreSQL contract coverage for M2D transactional writes."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from os import environ
from typing import Any
from uuid import UUID, uuid4

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
    write_response,
)
from novacommerce.schemas.writes import OrderCreateItemRequest, OrderCreateRequest
from novacommerce.seed.config import SeedConfig
from novacommerce.seed.ids import scenario_uuid
from novacommerce.seed.service import seed_database
from novacommerce.services.writes.orders import create_order

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

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


async def arrange_future_delivery_slots(engine: AsyncEngine) -> None:
    """Keep M2D slot-write tests independent of the canonical seed date."""

    today = datetime.now(UTC).date()
    seed_as_of = SeedConfig().as_of
    offset_days = max(1, (today - seed_as_of).days)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE delivery_slots "
                "SET service_date = service_date + CAST(:temporary_offset AS INTEGER)"
            ),
            {"temporary_offset": 1000},
        )
        await connection.execute(
            text(
                "UPDATE delivery_slots "
                "SET service_date = service_date "
                "+ CAST(:offset_days AS INTEGER) "
                "- CAST(:temporary_offset AS INTEGER)"
            ),
            {"offset_days": offset_days, "temporary_offset": 1000},
        )
        earliest = (
            await connection.execute(text("SELECT min(service_date) FROM delivery_slots"))
        ).scalar_one()
    assert earliest > today


@pytest_asyncio.fixture
async def live_app(database_url: str, engine: AsyncEngine) -> AsyncIterator[Any]:
    await clear_database(engine)
    settings = Settings(
        environment=Environment.TEST,
        database=DatabaseSettings(url=SecretStr(database_url)),
        service_token=SecretStr(TOKEN),
    )
    await seed_database(settings, SeedConfig())
    await arrange_future_delivery_slots(engine)
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


async def prepare_return_scenario(
    engine: AsyncEngine,
    order_id: UUID,
    *,
    delivered_days_ago: int,
    selected_item_quantity: int | None = None,
) -> tuple[UUID, datetime, datetime]:
    """Arrange one deterministic return scenario entirely in test DB state."""

    now = datetime.now(UTC)
    delivered_at = now - timedelta(days=delivered_days_ago)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "DELETE FROM return_items WHERE return_id IN "
                "(SELECT id FROM returns WHERE order_id = :order_id)"
            ),
            {"order_id": order_id},
        )
        await connection.execute(
            text("DELETE FROM returns WHERE order_id = :order_id"),
            {"order_id": order_id},
        )
        await connection.execute(
            text("UPDATE orders SET status = 'delivered' WHERE id = :order_id"),
            {"order_id": order_id},
        )
        await connection.execute(
            text(
                "UPDATE shipments SET status = 'delivered', delivered_at = :delivered_at "
                "WHERE order_id = :order_id"
            ),
            {"order_id": order_id, "delivered_at": delivered_at},
        )
        if selected_item_quantity is not None:
            await connection.execute(
                text(
                    "UPDATE order_items SET quantity = :quantity "
                    "WHERE id = (SELECT id FROM order_items "
                    "WHERE order_id = :order_id ORDER BY id LIMIT 1)"
                ),
                {"order_id": order_id, "quantity": selected_item_quantity},
            )
    return await order_item_id(engine, order_id), now, delivered_at


async def consumed_return_quantity(engine: AsyncEngine, item_id: UUID) -> int:
    return int(
        await scalar(
            engine,
            "SELECT coalesce(sum(ri.quantity), 0) FROM return_items ri "
            "JOIN returns r ON r.id = ri.return_id "
            "WHERE ri.order_item_id = :item_id "
            "AND r.status IN ('requested', 'approved', 'received', 'completed')",
            item_id=item_id,
        )
    )


async def assert_return_fixture(
    engine: AsyncEngine,
    order_id: UUID,
    item_id: UUID,
    *,
    now: datetime,
    delivered_at: datetime,
    requested_quantity: int,
    window_open: bool,
) -> None:
    async with engine.connect() as connection:
        order_status, shipment_status = (
            await connection.execute(
                text(
                    "SELECT o.status, s.status FROM orders o "
                    "JOIN shipments s ON s.order_id = o.id WHERE o.id = :order_id"
                ),
                {"order_id": order_id},
            )
        ).one()
    ordered_quantity = int(
        await scalar(
            engine, "SELECT quantity FROM order_items WHERE id = :item_id", item_id=item_id
        )
    )
    consumed = await consumed_return_quantity(engine, item_id)
    assert order_status == "delivered", "fixture precondition incorrect"
    assert shipment_status == "delivered", "fixture precondition incorrect"
    assert (now <= delivered_at + timedelta(days=30)) is window_open, (
        "fixture precondition incorrect"
    )
    assert consumed == 0, "fixture precondition incorrect"
    assert ordered_quantity - consumed >= requested_quantity, "fixture precondition incorrect"


async def run_race(*requests: Any) -> list[httpx.Response]:
    results = await asyncio.wait_for(asyncio.gather(*requests, return_exceptions=True), timeout=20)
    for result in results:
        if isinstance(result, BaseException):
            pytest.fail(f"concurrent request raised {result!r}")
    return [result for result in results if isinstance(result, httpx.Response)]


async def scalar(engine: AsyncEngine, statement: str, **params: object) -> Any:
    async with engine.connect() as connection:
        return (await connection.execute(text(statement), params)).scalar_one()


async def slot_state(engine: AsyncEngine, slot_id: UUID) -> tuple[int, int, int]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT capacity, reserved_count, "
                    "(SELECT count(*) FROM shipments WHERE delivery_slot_id = :slot_id) "
                    "FROM delivery_slots WHERE id = :slot_id"
                ),
                {"slot_id": slot_id},
            )
        ).one()
    return int(row[0]), int(row[1]), int(row[2])


async def order_count(engine: AsyncEngine, order_id: UUID) -> int:
    return int(
        await scalar(engine, "SELECT count(*) FROM orders WHERE id = :order_id", order_id=order_id)
    )


async def status_count(engine: AsyncEngine, table: str, statuses: tuple[str, ...]) -> int:
    placeholders = ", ".join(f":status_{index}" for index in range(len(statuses)))
    params = {f"status_{index}": status for index, status in enumerate(statuses)}
    return int(
        await scalar(
            engine,
            f"SELECT count(*) FROM {table} WHERE status IN ({placeholders})",
            **params,
        )
    )


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.critical_race
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

    delivered_item, return_now, delivered_at = await prepare_return_scenario(
        engine, delivered_29d, delivered_days_ago=29
    )
    await assert_return_fixture(
        engine,
        delivered_29d,
        delivered_item,
        now=return_now,
        delivered_at=delivered_at,
        requested_quantity=1,
        window_open=True,
    )
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
    expired_item, expired_now, expired_delivered_at = await prepare_return_scenario(
        engine, delivered_31d, delivered_days_ago=31
    )
    await assert_return_fixture(
        engine,
        delivered_31d,
        expired_item,
        now=expired_now,
        delivered_at=expired_delivered_at,
        requested_quantity=1,
        window_open=False,
    )
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
    before_concurrent = await counts(engine)
    concurrent = await run_race(
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
    assert sum("X-Idempotent-Replay" in response.headers for response in concurrent) == 1

    after_concurrent = await counts(engine)
    assert after_concurrent["orders"] - before_concurrent["orders"] == 1
    assert after_concurrent["commerce_events"] - before_concurrent["commerce_events"] == 1
    assert after_concurrent["idempotency_records"] - before_concurrent["idempotency_records"] == 1
    async with engine.connect() as connection:
        record = (
            await connection.execute(
                text(
                    "SELECT status, response_status FROM idempotency_records "
                    "WHERE key = 'm2d-concurrent-create-001'"
                )
            )
        ).one()
    assert record == ("completed", 201)

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
@pytest.mark.contract
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
@pytest.mark.concurrency
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
@pytest.mark.concurrency
async def test_m2d_real_mutation_failure_before_event_rolls_back_everything(
    live_app: Any,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del live_app
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    product = scenario_uuid(config, "product_standard_stock")
    key = "m2d-failure-before-event"
    request_body = OrderCreateRequest(
        items=[OrderCreateItemRequest(product_id=product, quantity=1)]
    )
    before = await counts(engine)

    async def fail_before_event(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError("injected failure before event")

    monkeypatch.setattr("novacommerce.services.writes.orders.append_event", fail_before_event)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as session:
        with pytest.raises(APIError) as error:
            await execute_idempotent_write(
                session,
                key=key,
                operation="order.create",
                customer_id=primary,
                fingerprint=request_fingerprint("order.create", primary, body=request_body),
                operation_fn=lambda active: create_order(
                    active,
                    customer_id=primary,
                    request=request_body,
                    idempotency_key=key,
                ),
            )
    assert error.value.code == "write_outcome_unknown"
    assert await counts(engine) == before


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_m2d_real_mutation_failure_after_event_rolls_back_everything(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    del live_app
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    product = scenario_uuid(config, "product_standard_stock")
    key = "m2d-failure-after-event"
    request_body = OrderCreateRequest(
        items=[OrderCreateItemRequest(product_id=product, quantity=1)]
    )
    before = await counts(engine)

    async def mutate_then_fail(active: AsyncSession) -> WriteOutcome:
        await create_order(
            active,
            customer_id=primary,
            request=request_body,
            idempotency_key=key,
        )
        raise RuntimeError("injected failure after event")

    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as session:
        with pytest.raises(APIError) as error:
            await execute_idempotent_write(
                session,
                key=key,
                operation="order.create",
                customer_id=primary,
                fingerprint=request_fingerprint("order.create", primary, body=request_body),
                operation_fn=mutate_then_fail,
            )
    assert error.value.code == "write_outcome_unknown"
    assert await counts(engine) == before


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_m2d_real_mutation_failure_after_completion_rolls_back_everything(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    del live_app
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    product = scenario_uuid(config, "product_standard_stock")
    key = "m2d-failure-after-completion"
    request_body = OrderCreateRequest(
        items=[OrderCreateItemRequest(product_id=product, quantity=1)]
    )
    before = await counts(engine)

    async def fail_before_commit() -> None:
        raise RuntimeError("injected failure before commit")

    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as session:
        with pytest.raises(APIError) as error:
            await execute_idempotent_write(
                session,
                key=key,
                operation="order.create",
                customer_id=primary,
                fingerprint=request_fingerprint("order.create", primary, body=request_body),
                operation_fn=lambda active: create_order(
                    active,
                    customer_id=primary,
                    request=request_body,
                    idempotency_key=key,
                ),
                commit_fn=fail_before_commit,
            )
    assert error.value.code == "write_outcome_unknown"
    assert await counts(engine) == before


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_m2d_ambiguous_commit_replays_committed_outcome(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    product = scenario_uuid(config, "product_standard_stock")
    key = "m2d-ambiguous-commit-test"
    request_body = OrderCreateRequest(
        items=[OrderCreateItemRequest(product_id=product, quantity=1)]
    )
    fingerprint = request_fingerprint("order.create", primary, body=request_body)
    before = await counts(engine)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    calls = 0
    first_body: dict[str, Any] = {}

    async def operation(active: AsyncSession) -> WriteOutcome:
        nonlocal calls
        calls += 1
        outcome = await create_order(
            active,
            customer_id=primary,
            request=request_body,
            idempotency_key=key,
        )
        first_body.update(outcome.body)
        return outcome

    async with sessions() as session:

        async def commit_then_lose_ack() -> None:
            await session.commit()
            raise RuntimeError("injected acknowledgement loss")

        with pytest.raises(APIError) as error:
            await execute_idempotent_write(
                session,
                key=key,
                operation="order.create",
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
            operation="order.create",
            customer_id=primary,
            fingerprint=fingerprint,
            operation_fn=operation,
        )
    assert retry.replayed is True
    assert retry.outcome.status_code == 201
    assert retry.outcome.body == first_body
    assert calls == 1
    assert write_response(retry).headers["X-Idempotent-Replay"] == "true"
    after = await counts(engine)
    assert after["orders"] - before["orders"] == 1
    assert after["commerce_events"] - before["commerce_events"] == 1
    assert after["idempotency_records"] - before["idempotency_records"] == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_m2d_unpersisted_ambiguous_commit_retries_real_mutation_once(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    del live_app
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    product = scenario_uuid(config, "product_standard_stock")
    key = "m2d-unpersisted-ambiguous-commit"
    request_body = OrderCreateRequest(
        items=[OrderCreateItemRequest(product_id=product, quantity=1)]
    )
    fingerprint = request_fingerprint("order.create", primary, body=request_body)
    before = await counts(engine)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    calls = 0

    async def operation(active: AsyncSession) -> WriteOutcome:
        nonlocal calls
        calls += 1
        return await create_order(
            active,
            customer_id=primary,
            request=request_body,
            idempotency_key=key,
        )

    async def fail_before_persisted_commit() -> None:
        raise RuntimeError("injected pre-commit acknowledgement failure")

    async with sessions() as session:
        with pytest.raises(APIError) as error:
            await execute_idempotent_write(
                session,
                key=key,
                operation="order.create",
                customer_id=primary,
                fingerprint=fingerprint,
                operation_fn=operation,
                commit_fn=fail_before_persisted_commit,
            )
    assert error.value.code == "write_outcome_unknown"
    assert await counts(engine) == before

    async with sessions() as retry_session:
        retry = await execute_idempotent_write(
            retry_session,
            key=key,
            operation="order.create",
            customer_id=primary,
            fingerprint=fingerprint,
            operation_fn=operation,
        )
    assert retry.replayed is False
    assert calls == 2
    after = await counts(engine)
    assert after["orders"] - before["orders"] == 1
    assert after["commerce_events"] - before["commerce_events"] == 1
    assert after["idempotency_records"] - before["idempotency_records"] == 1


@pytest.mark.asyncio
@pytest.mark.contract
async def test_m2d_postgres_same_key_rejects_target_operation_and_customer_reuse(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    other = scenario_uuid(config, "customer_other")
    standard_product = scenario_uuid(config, "product_standard_stock")

    async with engine.connect() as connection:
        owned_orders = list(
            (
                await connection.execute(
                    text(
                        "SELECT o.id FROM orders o JOIN shipments s ON s.order_id = o.id "
                        "WHERE o.customer_id = :customer_id AND o.status = 'confirmed' "
                        "AND s.status = 'label_created' ORDER BY o.id LIMIT 2"
                    ),
                    {"customer_id": primary},
                )
            ).scalars()
        )
    assert len(owned_orders) == 2

    first_target = await request(
        live_app,
        "POST",
        f"/v1/orders/{owned_orders[0]}/cancel",
        customer_id=primary,
        key="m2d-same-target-key",
    )
    different_target = await request(
        live_app,
        "POST",
        f"/v1/orders/{owned_orders[1]}/cancel",
        customer_id=primary,
        key="m2d-same-target-key",
    )
    assert first_target.status_code == 200
    assert different_target.status_code == 409
    assert different_target.json()["error"]["code"] == "idempotency_key_reused"

    first_operation = await request(
        live_app,
        "POST",
        "/v1/support-tickets",
        customer_id=primary,
        key="m2d-same-operation-key",
        body={"subject": "same operation", "description": "first"},
    )
    different_operation = await request(
        live_app,
        "POST",
        "/v1/orders",
        customer_id=primary,
        key="m2d-same-operation-key",
        body={"items": [{"product_id": str(standard_product), "quantity": 1}]},
    )
    assert first_operation.status_code == 201
    assert different_operation.status_code == 409
    assert different_operation.json()["error"]["code"] == "idempotency_key_reused"

    first_customer = await request(
        live_app,
        "POST",
        "/v1/support-tickets",
        customer_id=primary,
        key="m2d-same-customer-key",
        body={"subject": "customer identity", "description": "primary"},
    )
    different_customer = await request(
        live_app,
        "POST",
        "/v1/support-tickets",
        customer_id=other,
        key="m2d-same-customer-key",
        body={"subject": "customer identity", "description": "primary"},
    )
    assert first_customer.status_code == 201
    assert different_customer.status_code == 409
    assert different_customer.json()["error"]["code"] == "idempotency_key_reused"
    assert different_customer.json() != first_customer.json()


@pytest.mark.asyncio
@pytest.mark.contract
async def test_m2d_postgres_pre_execution_and_deterministic_rejection_counts(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    shipped = scenario_uuid(config, "order_already_shipped")
    before = await counts(engine)

    invalid_body = await request(
        live_app,
        "POST",
        "/v1/orders",
        customer_id=primary,
        key="m2d-invalid-body-counts",
        body={"items": []},
    )
    assert invalid_body.status_code == 422
    after_invalid = await counts(engine)
    assert after_invalid["orders"] - before["orders"] == 0
    assert after_invalid["commerce_events"] - before["commerce_events"] == 0
    assert after_invalid["idempotency_records"] - before["idempotency_records"] == 0

    rejection_before = await counts(engine)
    rejected = await request(
        live_app,
        "POST",
        f"/v1/orders/{shipped}/cancel",
        customer_id=primary,
        key="m2d-deterministic-rejection-counts",
    )
    rejection_after = await counts(engine)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "order_not_cancellable"
    assert rejection_after["orders"] - rejection_before["orders"] == 0
    assert rejection_after["commerce_events"] - rejection_before["commerce_events"] == 0
    assert rejection_after["idempotency_records"] - rejection_before["idempotency_records"] == 1
    record = await scalar(
        engine,
        "SELECT count(*) FROM idempotency_records WHERE key = :key "
        "AND status = 'completed' AND response_status = 409",
        key="m2d-deterministic-rejection-counts",
    )
    assert record == 1

    replay = await request(
        live_app,
        "POST",
        f"/v1/orders/{shipped}/cancel",
        customer_id=primary,
        key="m2d-deterministic-rejection-counts",
    )
    assert replay.status_code == rejected.status_code
    assert replay.json() == rejected.json()
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert await counts(engine) == rejection_after


@pytest.mark.asyncio
@pytest.mark.contract
async def test_m2d_postgres_same_slot_reschedule_is_idempotent_without_event(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    shipped = scenario_uuid(config, "order_already_shipped")
    slot = scenario_uuid(config, "slot_available")
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE shipments SET delivery_slot_id = :slot_id WHERE order_id = :order_id"),
            {"slot_id": slot, "order_id": shipped},
        )
        await connection.execute(
            text(
                "UPDATE delivery_slots SET reserved_count = reserved_count + 1 WHERE id = :slot_id"
            ),
            {"slot_id": slot},
        )

    before_counts = await counts(engine)
    before_slot = await slot_state(engine, slot)
    first = await request(
        live_app,
        "POST",
        f"/v1/orders/{shipped}/reschedule",
        customer_id=primary,
        key="m2d-same-slot-new-key",
        body={"delivery_slot_id": str(slot)},
    )
    after_first = await counts(engine)
    after_slot = await slot_state(engine, slot)
    assert first.status_code == 200
    assert after_slot == before_slot
    assert after_first["commerce_events"] - before_counts["commerce_events"] == 0
    assert after_first["idempotency_records"] - before_counts["idempotency_records"] == 1
    assigned = await scalar(
        engine,
        "SELECT delivery_slot_id FROM shipments WHERE order_id = :order_id",
        order_id=shipped,
    )
    assert str(assigned) == str(slot)

    replay = await request(
        live_app,
        "POST",
        f"/v1/orders/{shipped}/reschedule",
        customer_id=primary,
        key="m2d-same-slot-new-key",
        body={"delivery_slot_id": str(slot)},
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["X-Idempotent-Replay"] == "true"
    assert await counts(engine) == after_first
    assert await slot_state(engine, slot) == before_slot


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.critical_race
async def test_m2d_postgres_final_inventory_unit_race(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    product = scenario_uuid(config, "product_standard_stock")
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE products SET stock = 1 WHERE id = :product_id"),
            {"product_id": product},
        )
    before = await counts(engine)
    body = {"items": [{"product_id": str(product), "quantity": 1}]}
    responses = await run_race(
        request(
            live_app, "POST", "/v1/orders", customer_id=primary, key="m2d-stock-race-a", body=body
        ),
        request(
            live_app, "POST", "/v1/orders", customer_id=primary, key="m2d-stock-race-b", body=body
        ),
    )
    codes = [response.json().get("error", {}).get("code") for response in responses]
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert codes.count("insufficient_stock") == 1
    after = await counts(engine)
    assert after["orders"] - before["orders"] == 1
    assert after["commerce_events"] - before["commerce_events"] == 1
    assert await scalar(engine, "SELECT stock FROM products WHERE id = :id", id=product) == 0


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.critical_race
async def test_m2d_postgres_double_cancellation_restores_inventory_once(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    cancellable = scenario_uuid(config, "order_cancellable")
    async with engine.connect() as connection:
        item = (
            await connection.execute(
                text(
                    "SELECT product_id, quantity FROM order_items "
                    "WHERE order_id = :order_id ORDER BY id LIMIT 1"
                ),
                {"order_id": cancellable},
            )
        ).one()
    product_id, quantity = UUID(str(item[0])), int(item[1])
    stock_before = int(
        await scalar(engine, "SELECT stock FROM products WHERE id = :id", id=product_id)
    )
    before = await counts(engine)
    responses = await run_race(
        request(
            live_app,
            "POST",
            f"/v1/orders/{cancellable}/cancel",
            customer_id=primary,
            key="m2d-cancel-race-a",
        ),
        request(
            live_app,
            "POST",
            f"/v1/orders/{cancellable}/cancel",
            customer_id=primary,
            key="m2d-cancel-race-b",
        ),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert (
        sum(
            response.json().get("error", {}).get("code") == "order_not_cancellable"
            for response in responses
        )
        == 1
    )
    after = await counts(engine)
    assert after["commerce_events"] - before["commerce_events"] == 1
    assert (
        int(await scalar(engine, "SELECT stock FROM products WHERE id = :id", id=product_id))
        == stock_before + quantity
    )
    assert (
        await scalar(engine, "SELECT status FROM orders WHERE id = :id", id=cancellable)
        == "cancelled"
    )
    assert (
        await scalar(engine, "SELECT status FROM shipments WHERE order_id = :id", id=cancellable)
        == "cancelled"
    )


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_m2d_postgres_cancel_vs_reschedule_has_legal_final_state(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    order_id = scenario_uuid(config, "order_already_shipped")
    target = scenario_uuid(config, "slot_available")
    async with engine.connect() as connection:
        product_id, quantity = (
            await connection.execute(
                text(
                    "SELECT product_id, quantity FROM order_items "
                    "WHERE order_id = :order_id ORDER BY id LIMIT 1"
                ),
                {"order_id": order_id},
            )
        ).one()
    product_id = UUID(str(product_id))
    quantity = int(quantity)
    stock_before = int(
        await scalar(engine, "SELECT stock FROM products WHERE id = :id", id=product_id)
    )
    responses = await run_race(
        request(
            live_app,
            "POST",
            f"/v1/orders/{order_id}/cancel",
            customer_id=primary,
            key="m2d-cancel-reschedule-cancel",
        ),
        request(
            live_app,
            "POST",
            f"/v1/orders/{order_id}/reschedule",
            customer_id=primary,
            key="m2d-cancel-reschedule-move",
            body={"delivery_slot_id": str(target)},
        ),
    )
    assert all(response.status_code in {200, 409} for response in responses)
    assert all(response.status_code != 500 for response in responses)
    order_status = await scalar(engine, "SELECT status FROM orders WHERE id = :id", id=order_id)
    async with engine.connect() as connection:
        shipment_status, shipment_slot = (
            await connection.execute(
                text("SELECT status, delivery_slot_id FROM shipments WHERE order_id = :id"),
                {"id": order_id},
            )
        ).one()
    assert (order_status, shipment_status) in {
        ("shipped", "in_transit"),
        ("cancelled", "cancelled"),
    }
    stock_after = int(
        await scalar(engine, "SELECT stock FROM products WHERE id = :id", id=product_id)
    )
    assert stock_after >= 0
    assert stock_after == (stock_before + quantity if order_status == "cancelled" else stock_before)
    if shipment_slot is not None:
        capacity, reserved, references = await slot_state(engine, UUID(str(shipment_slot)))
        assert 0 <= reserved <= capacity
        assert reserved == references


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.critical_race
async def test_m2d_postgres_final_slot_race_allows_one_shipment(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    target = scenario_uuid(config, "slot_one_remaining")
    async with engine.connect() as connection:
        candidates = list(
            (
                await connection.execute(
                    text(
                        "SELECT o.id FROM orders o JOIN shipments s ON s.order_id = o.id "
                        "WHERE o.customer_id = :customer_id AND o.status = 'confirmed' "
                        "AND s.status = 'label_created' AND s.delivery_slot_id IS NULL "
                        "ORDER BY o.id LIMIT 2"
                    ),
                    {"customer_id": primary},
                )
            ).scalars()
        )
    assert len(candidates) == 2
    before = await counts(engine)
    responses = await run_race(
        request(
            live_app,
            "POST",
            f"/v1/orders/{candidates[0]}/reschedule",
            customer_id=primary,
            key="m2d-final-slot-a",
            body={"delivery_slot_id": str(target)},
        ),
        request(
            live_app,
            "POST",
            f"/v1/orders/{candidates[1]}/reschedule",
            customer_id=primary,
            key="m2d-final-slot-b",
            body={"delivery_slot_id": str(target)},
        ),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert (
        sum(
            response.json().get("error", {}).get("code") == "delivery_slot_full"
            for response in responses
        )
        == 1
    )
    capacity, reserved, references = await slot_state(engine, target)
    assert (capacity, reserved, references) == (20, 20, 20)
    after = await counts(engine)
    assert after["commerce_events"] - before["commerce_events"] == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_m2d_postgres_opposite_reschedules_preserve_slot_invariants(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    async with engine.connect() as connection:
        candidates = list(
            (
                await connection.execute(
                    text(
                        "SELECT o.id FROM orders o JOIN shipments s ON s.order_id = o.id "
                        "WHERE o.customer_id = :customer_id AND o.status = 'confirmed' "
                        "AND s.status = 'label_created' AND s.delivery_slot_id IS NULL "
                        "ORDER BY o.id LIMIT 2"
                    ),
                    {"customer_id": primary},
                )
            ).scalars()
        )
        slots = list(
            (
                await connection.execute(
                    text(
                        "SELECT id FROM delivery_slots WHERE capacity - reserved_count >= 2 "
                        "ORDER BY id LIMIT 2"
                    )
                )
            ).scalars()
        )
    assert len(candidates) == 2
    assert len(slots) == 2
    first_slot, second_slot = UUID(str(slots[0])), UUID(str(slots[1]))
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE shipments SET delivery_slot_id = :slot WHERE order_id = :order_id"),
            {"slot": first_slot, "order_id": candidates[0]},
        )
        await connection.execute(
            text("UPDATE shipments SET delivery_slot_id = :slot WHERE order_id = :order_id"),
            {"slot": second_slot, "order_id": candidates[1]},
        )
        await connection.execute(
            text(
                "UPDATE delivery_slots SET reserved_count = reserved_count + 1 WHERE id IN (:first, :second)"
            ),
            {"first": first_slot, "second": second_slot},
        )
    responses = await run_race(
        request(
            live_app,
            "POST",
            f"/v1/orders/{candidates[0]}/reschedule",
            customer_id=primary,
            key="m2d-opposite-a",
            body={"delivery_slot_id": str(second_slot)},
        ),
        request(
            live_app,
            "POST",
            f"/v1/orders/{candidates[1]}/reschedule",
            customer_id=primary,
            key="m2d-opposite-b",
            body={"delivery_slot_id": str(first_slot)},
        ),
    )
    assert all(response.status_code == 200 for response in responses)
    for slot_id in (first_slot, second_slot):
        capacity, reserved, references = await slot_state(engine, slot_id)
        assert 0 <= reserved <= capacity
        assert reserved == references


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.critical_race
async def test_m2d_postgres_final_returnable_quantity_race(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    order_id = scenario_uuid(config, "order_delivered_29d")
    item_id, race_now, race_delivered_at = await prepare_return_scenario(
        engine,
        order_id,
        delivered_days_ago=29,
        selected_item_quantity=1,
    )
    await assert_return_fixture(
        engine,
        order_id,
        item_id,
        now=race_now,
        delivered_at=race_delivered_at,
        requested_quantity=1,
        window_open=True,
    )
    before = await counts(engine)
    body = {
        "order_id": str(order_id),
        "reason": "concurrent return",
        "items": [{"order_item_id": str(item_id), "quantity": 1}],
    }
    responses = await run_race(
        request(
            live_app, "POST", "/v1/returns", customer_id=primary, key="m2d-return-race-a", body=body
        ),
        request(
            live_app, "POST", "/v1/returns", customer_id=primary, key="m2d-return-race-b", body=body
        ),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert (
        sum(
            response.json().get("error", {}).get("code") == "return_quantity_exceeded"
            for response in responses
        )
        == 1
    )
    returned_quantity = await scalar(
        engine,
        "SELECT coalesce(sum(ri.quantity), 0) FROM return_items ri "
        "JOIN returns r ON r.id = ri.return_id WHERE r.order_id = :order_id "
        "AND r.status IN ('requested', 'approved', 'received', 'completed')",
        order_id=order_id,
    )
    assert returned_quantity == 1
    after = await counts(engine)
    assert after["commerce_events"] - before["commerce_events"] == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.critical_race
async def test_m2d_postgres_refund_remaining_amount_race(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as connection:
        customer_id, order_id, order_total = (
            await connection.execute(
                text(
                    "SELECT o.customer_id, o.id, o.total FROM orders o "
                    "WHERE o.status IN ('delivered', 'cancelled') AND o.total >= 800 "
                    "AND NOT EXISTS (SELECT 1 FROM refunds r WHERE r.order_id = o.id "
                    "AND r.status IN ('approved', 'pending_manual_approval', 'completed')) "
                    "ORDER BY o.id LIMIT 1"
                )
            )
        ).one()
    customer_id = UUID(str(customer_id))
    order_id = UUID(str(order_id))
    order_total = Decimal(str(order_total))
    existing_refund = order_total - Decimal("600.00")
    assert existing_refund > Decimal("0.00")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO refunds "
                "(id, order_id, amount, status, reason, requires_manual_approval, created_at) "
                "VALUES (:id, :order_id, :amount, 'approved', 'existing refundable amount', false, now())"
            ),
            {"id": uuid4(), "order_id": order_id, "amount": existing_refund},
        )
    before = await counts(engine)
    before_refunded = Decimal(
        str(
            await scalar(
                engine,
                "SELECT coalesce(sum(amount), 0) FROM refunds WHERE order_id = :order_id "
                "AND status IN ('approved', 'pending_manual_approval', 'completed')",
                order_id=order_id,
            )
        )
    )
    assert order_total - before_refunded == Decimal("600.00")
    body = {"amount": "400.00", "reason": "concurrent refund"}
    responses = await run_race(
        request(
            live_app,
            "POST",
            f"/v1/orders/{order_id}/refunds",
            customer_id=customer_id,
            key="m2d-refund-race-a",
            body=body,
        ),
        request(
            live_app,
            "POST",
            f"/v1/orders/{order_id}/refunds",
            customer_id=customer_id,
            key="m2d-refund-race-b",
            body=body,
        ),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert (
        sum(
            response.json().get("error", {}).get("code") == "refund_amount_exceeds_remaining"
            for response in responses
        )
        == 1
    )
    amount = Decimal(
        str(
            await scalar(
                engine,
                "SELECT coalesce(sum(amount), 0) FROM refunds WHERE order_id = :order_id "
                "AND status IN ('approved', 'pending_manual_approval', 'completed')",
                order_id=order_id,
            )
        )
    )
    assert amount - before_refunded <= Decimal("600.00")
    after = await counts(engine)
    assert after["commerce_events"] - before["commerce_events"] == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_m2d_postgres_duplicate_ticket_same_key_creates_once(
    live_app: Any,
    engine: AsyncEngine,
) -> None:
    config = SeedConfig()
    primary = scenario_uuid(config, "customer_primary")
    before = await counts(engine)
    body = {"subject": "race ticket", "description": "same key"}
    responses = await run_race(
        request(
            live_app,
            "POST",
            "/v1/support-tickets",
            customer_id=primary,
            key="m2d-ticket-race",
            body=body,
        ),
        request(
            live_app,
            "POST",
            "/v1/support-tickets",
            customer_id=primary,
            key="m2d-ticket-race",
            body=body,
        ),
    )
    assert all(response.status_code == 201 for response in responses)
    assert responses[0].json() == responses[1].json()
    assert sum("X-Idempotent-Replay" in response.headers for response in responses) == 1
    after = await counts(engine)
    assert after["support_tickets"] - before["support_tickets"] == 1
    assert after["commerce_events"] - before["commerce_events"] == 1
    assert after["idempotency_records"] - before["idempotency_records"] == 1
