"""Order response construction contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from novacommerce.db.models.order import OrderStatus
from novacommerce.services.writes.common import order_response


def test_order_response_can_use_explicit_locked_items_without_lazy_relationship_io() -> None:
    order_id = UUID("00000000-0000-0000-0000-000000000001")
    customer_id = UUID("00000000-0000-0000-0000-000000000002")
    item = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        product_id=UUID("00000000-0000-0000-0000-000000000004"),
        product=SimpleNamespace(sku="SKU", name="Product"),
        quantity=1,
        unit_price=Decimal("10.00"),
    )
    order = SimpleNamespace(
        id=order_id,
        customer_id=customer_id,
        status=OrderStatus.CANCELLED,
        total=Decimal("10.00"),
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        updated_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    response = order_response(cast(Any, order), items=cast(Any, [item]))
    assert response.items[0].line_total == Decimal("10.00")
