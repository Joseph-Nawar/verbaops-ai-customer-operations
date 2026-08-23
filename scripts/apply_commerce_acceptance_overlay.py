"""Add time-relative HTTP acceptance fixtures without changing canonical seed rows."""

import asyncio
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from novacommerce.db.models import (
    Customer,
    DeliverySlot,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    Shipment,
    ShipmentStatus,
)


def parse_acceptance_as_of(value: str) -> datetime:
    try:
        from scripts.acceptance_time import parse_acceptance_as_of as _parse_scripts
    except ModuleNotFoundError:  # pragma: no cover - used by the mounted Compose script
        from acceptance_time import (  # type: ignore[import-not-found]
            parse_acceptance_as_of as _parse_mounted,
        )

        return cast(Callable[[str], datetime], _parse_mounted)(value)
    return _parse_scripts(value)


def _uuid(manifest: dict[str, object], key: str) -> UUID:
    overlay_ids = manifest["overlay_ids"]
    if not isinstance(overlay_ids, dict):
        raise ValueError("overlay_ids must be an object")
    value = overlay_ids[key]
    if not isinstance(value, str):
        raise ValueError(f"overlay ID {key!r} must be a string")
    return UUID(value)


def _scenario(manifest: dict[str, object], key: str) -> UUID:
    scenario_ids = manifest["scenario_ids"]
    if not isinstance(scenario_ids, dict):
        raise ValueError("scenario_ids must be an object")
    value = scenario_ids[key]
    if not isinstance(value, str):
        raise ValueError(f"scenario ID {key!r} must be a string")
    return UUID(value)


async def apply_overlay(database_url: str, manifest_path: Path) -> None:
    """Insert the disposable overlay in one transaction."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("scenario manifest must be an object")
    acceptance_as_of = parse_acceptance_as_of(os.environ.get("ACCEPTANCE_AS_OF", ""))
    rows = build_overlay_rows(manifest, acceptance_as_of)
    primary_id = _scenario(manifest, "customer_primary")
    recent_order_id = _uuid(manifest, "recent_delivered_order")
    reschedule_order_id = _uuid(manifest, "reschedulable_order")

    engine = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session, session.begin():
            primary_exists = await session.scalar(
                select(Customer.id).where(Customer.id == primary_id)
            )
            if primary_exists is None:
                raise ValueError("canonical customer_primary is missing")
            existing = await session.scalar(
                select(Order.id).where(Order.id.in_([recent_order_id, reschedule_order_id]))
            )
            ensure_overlay_absent(existing)
            await session.execute(insert(Product), rows["products"])
            await session.execute(insert(DeliverySlot), rows["delivery_slots"])
            await session.execute(insert(Order), rows["orders"])
            await session.execute(insert(OrderItem), rows["order_items"])
            await session.execute(insert(Shipment), rows["shipments"])
    finally:
        await engine.dispose()


def ensure_overlay_absent(existing_order_id: UUID | None) -> None:
    if existing_order_id is not None:
        raise ValueError("acceptance overlay already exists")


def build_overlay_rows(
    manifest: dict[str, object], acceptance_as_of: datetime
) -> dict[str, list[dict[str, object]]]:
    """Build deterministic disposable rows without consulting wall-clock time."""
    if acceptance_as_of.tzinfo is None or acceptance_as_of.utcoffset() is None:
        raise ValueError("acceptance_as_of must include a timezone")
    now = acceptance_as_of.astimezone(UTC).replace(microsecond=0)
    today = now.date()
    primary_id = _scenario(manifest, "customer_primary")
    overlay_product_id = _uuid(manifest, "overlay_product")
    recent_order_id = _uuid(manifest, "recent_delivered_order")
    recent_item_id = _uuid(manifest, "recent_order_item")
    reschedule_order_id = _uuid(manifest, "reschedulable_order")
    reschedule_item_id = _uuid(manifest, "reschedulable_order_item")
    slot_x_id = _uuid(manifest, "slot_x")
    slot_y_id = _uuid(manifest, "slot_y")
    created_at = now
    # Stay outside the canonical seed's 30-day window while remaining future-relative.
    future_x = today + timedelta(days=40)
    future_y = today + timedelta(days=41)
    return {
        "products": [
            {
                "id": overlay_product_id,
                "sku": "ACCEPTANCE-OVERLAY-001",
                "name": "Acceptance Overlay Device",
                "description": "Fictional disposable acceptance fixture product.",
                "price": Decimal("25.00"),
                "stock": 100,
                "active": True,
                "created_at": created_at,
                "updated_at": created_at,
            }
        ],
        "delivery_slots": [
            {
                "id": slot_x_id,
                "service_date": future_x,
                "window_start": time(9, 0, tzinfo=UTC),
                "window_end": time(11, 0, tzinfo=UTC),
                "capacity": 20,
                "reserved_count": 1,
            },
            {
                "id": slot_y_id,
                "service_date": future_y,
                "window_start": time(9, 0, tzinfo=UTC),
                "window_end": time(11, 0, tzinfo=UTC),
                "capacity": 20,
                "reserved_count": 0,
            },
        ],
        "orders": [
            {
                "id": recent_order_id,
                "customer_id": primary_id,
                "status": OrderStatus.DELIVERED.value,
                "total": Decimal("25.00"),
                "created_at": now - timedelta(days=2),
                "updated_at": now - timedelta(days=1),
                "cancelled_at": None,
            },
            {
                "id": reschedule_order_id,
                "customer_id": primary_id,
                "status": OrderStatus.CONFIRMED.value,
                "total": Decimal("25.00"),
                "created_at": created_at,
                "updated_at": created_at,
                "cancelled_at": None,
            },
        ],
        "order_items": [
            {
                "id": recent_item_id,
                "order_id": recent_order_id,
                "product_id": overlay_product_id,
                "quantity": 1,
                "unit_price": Decimal("25.00"),
            },
            {
                "id": reschedule_item_id,
                "order_id": reschedule_order_id,
                "product_id": overlay_product_id,
                "quantity": 1,
                "unit_price": Decimal("25.00"),
            },
        ],
        "shipments": [
            {
                "id": _uuid(manifest, "reschedulable_shipment"),
                "order_id": reschedule_order_id,
                "carrier": "Acceptance Carrier",
                "tracking_number": "ACCEPTANCE-OVERLAY-SHIPMENT",
                "status": ShipmentStatus.LABEL_CREATED.value,
                "estimated_delivery": now + timedelta(days=2),
                "delivered_at": None,
                "delivery_slot_id": slot_x_id,
            },
            {
                "id": _uuid(manifest, "recent_delivered_shipment"),
                "order_id": recent_order_id,
                "carrier": "Acceptance Carrier",
                "tracking_number": "ACCEPTANCE-OVERLAY-DELIVERED",
                "status": ShipmentStatus.DELIVERED.value,
                "estimated_delivery": now - timedelta(days=1),
                "delivered_at": now - timedelta(days=1),
                "delivery_slot_id": None,
            },
        ],
    }


def main() -> int:
    database_url = os.environ.get("NOVACOMMERCE_DATABASE__URL", "")
    manifest_path = Path(os.environ.get("ACCEPTANCE_SCENARIO_MANIFEST", ""))
    acceptance_as_of = os.environ.get("ACCEPTANCE_AS_OF", "")
    if not database_url or not manifest_path or not acceptance_as_of:
        raise SystemExit("acceptance database URL, manifest, and ACCEPTANCE_AS_OF are required")
    asyncio.run(apply_overlay(database_url, manifest_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
