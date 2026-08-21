"""NovaCommerce ORM metadata and constraint contracts."""

from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, UniqueConstraint

from novacommerce.db.base import Base
from novacommerce.db.models import (
    CommerceEvent,
    DeliverySlot,
    IdempotencyRecord,
    IdempotencyStatus,
    Order,
    OrderItem,
    OrderStatus,
    RefundStatus,
    ReturnStatus,
    ShipmentStatus,
    SupportTicketStatus,
)


def test_metadata_contains_exact_commerce_tables() -> None:
    assert set(Base.metadata.tables) == {
        "customers",
        "products",
        "orders",
        "order_items",
        "shipments",
        "delivery_slots",
        "refunds",
        "returns",
        "return_items",
        "support_tickets",
        "idempotency_records",
        "commerce_events",
    }


def test_all_status_enums_are_string_backed_with_expected_values() -> None:
    assert [status.value for status in OrderStatus] == [
        "pending",
        "confirmed",
        "processing",
        "shipped",
        "delivered",
        "cancelled",
    ]
    assert [status.value for status in ShipmentStatus] == [
        "pending",
        "label_created",
        "in_transit",
        "out_for_delivery",
        "delivered",
        "exception",
        "cancelled",
    ]
    assert [status.value for status in RefundStatus] == [
        "approved",
        "pending_manual_approval",
        "rejected",
        "completed",
    ]
    assert [status.value for status in ReturnStatus] == [
        "requested",
        "approved",
        "rejected",
        "received",
        "completed",
    ]
    assert [status.value for status in SupportTicketStatus] == ["open", "in_progress", "closed"]
    assert [status.value for status in IdempotencyStatus] == ["in_progress", "completed"]


def test_model_columns_use_uuid_and_decimal_money_types() -> None:
    assert str(Order.__table__.c.id.type).upper().startswith("UUID")
    for table_name, column_name in (
        ("products", "price"),
        ("orders", "total"),
        ("order_items", "unit_price"),
        ("refunds", "amount"),
    ):
        column = Base.metadata.tables[table_name].c[column_name]
        assert isinstance(column.type, Numeric)
        assert column.type.precision == 12
        assert column.type.scale == 2
        assert column.type.asdecimal is True
        assert column.type.python_type is Decimal


def constraint_names(table_name: str) -> set[str]:
    return {
        constraint.name
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint.name, str)
    }


def test_required_named_constraints_exist() -> None:
    assert "uq_customers_email" in constraint_names("customers")
    assert "uq_products_sku" in constraint_names("products")
    assert "ck_products_price_non_negative" in constraint_names("products")
    assert "ck_products_stock_non_negative" in constraint_names("products")
    assert "ck_order_items_quantity_positive" in constraint_names("order_items")
    assert "ck_order_items_unit_price_non_negative" in constraint_names("order_items")
    assert "uq_shipments_order_id" in constraint_names("shipments")
    assert "uq_shipments_tracking_number" in constraint_names("shipments")
    assert "ck_delivery_slots_capacity_positive" in constraint_names("delivery_slots")
    assert "ck_delivery_slots_reserved_non_negative" in constraint_names("delivery_slots")
    assert "ck_delivery_slots_reserved_within_capacity" in constraint_names("delivery_slots")
    assert "ck_delivery_slots_window_order" in constraint_names("delivery_slots")
    assert "uq_delivery_slots_window" in constraint_names("delivery_slots")
    assert "ck_refunds_amount_positive" in constraint_names("refunds")
    assert "ck_return_items_quantity_positive" in constraint_names("return_items")
    assert "uq_return_items_return_order_item" in constraint_names("return_items")


def test_constraints_are_real_sqlalchemy_constraints() -> None:
    products = Base.metadata.tables["products"]
    assert any(isinstance(constraint, CheckConstraint) for constraint in products.constraints)
    assert any(isinstance(constraint, UniqueConstraint) for constraint in products.constraints)
    assert getattr(Order.__table__.c.status.type, "native_enum", True) is False
    assert isinstance(DeliverySlot.__table__.c.capacity.type.python_type(1), int)
    assert IdempotencyRecord.__table__.c.response_body.type.__class__.__name__ == "JSONB"
    assert CommerceEvent.__table__.c.payload.type.__class__.__name__ == "JSONB"


def test_required_foreign_keys_are_explicit() -> None:
    assert (
        str(next(iter(Order.__table__.c.customer_id.foreign_keys)).target_fullname)
        == "customers.id"
    )
    assert (
        str(next(iter(OrderItem.__table__.c.order_id.foreign_keys)).target_fullname) == "orders.id"
    )
