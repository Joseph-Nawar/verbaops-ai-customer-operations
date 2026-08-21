"""Pure deterministic NovaCommerce dataset construction and validation."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from faker import Faker

from novacommerce.seed.config import SeedConfig
from novacommerce.seed.ids import deterministic_uuid, scenario_uuid
from novacommerce.seed.scenarios import SeedScenario

Row = dict[str, Any]

ORDER_STATUS_COUNTS = {
    "pending": 800,
    "confirmed": 1_200,
    "processing": 1_500,
    "shipped": 1_800,
    "delivered": 4_000,
    "cancelled": 700,
}
REFUND_STATUS_COUNTS = {
    "approved": 300,
    "pending_manual_approval": 200,
    "rejected": 150,
    "completed": 150,
}
RETURN_STATUS_COUNTS = {
    "requested": 200,
    "approved": 150,
    "rejected": 100,
    "received": 75,
    "completed": 75,
}
TICKET_STATUS_COUNTS = {"open": 250, "in_progress": 150, "closed": 100}
WINDOWS = ((9, 11), (11, 13), (13, 15), (15, 17), (17, 19), (19, 21))
PROTECTED_ORDER_SCENARIOS = {
    "order_refund_499_99",
    "order_refund_500_00",
    "order_refund_501_00",
}


def _derived_seed(seed: int, label: str) -> int:
    """Derive an independent integer without Python's process-randomized hash."""

    return (
        seed * 1_000_003 + sum((index + 1) * ord(char) for index, char in enumerate(label))
    ) & 0xFFFFFFFF


def _uuid(seed: int, entity: str, index: int) -> UUID:
    return deterministic_uuid(seed, entity, f"index:{index:05d}")


def _scenario(config: SeedConfig, name: str) -> UUID:
    return scenario_uuid(config, SeedScenario(name))


def _faker(locale: str, seed: int, label: str) -> Faker:
    generator = Faker(locale)
    generator.seed_instance(_derived_seed(seed, label))
    return generator


@dataclass(slots=True)
class SeedDataset:
    """Generated rows, scenario references, and their canonical fingerprint."""

    seed: int
    as_of: date
    customers: list[Row]
    products: list[Row]
    orders: list[Row]
    order_items: list[Row]
    shipments: list[Row]
    delivery_slots: list[Row]
    refunds: list[Row]
    returns: list[Row]
    return_items: list[Row]
    support_tickets: list[Row]
    idempotency_records: list[Row]
    commerce_events: list[Row]
    scenario_ids: dict[str, UUID]

    @property
    def counts(self) -> dict[str, int]:
        return {
            name: len(getattr(self, name))
            for name in (
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
            )
        }

    @property
    def fingerprint(self) -> str:
        payload = {
            "seed": self.seed,
            "as_of": self.as_of.isoformat(),
            "scenario_ids": self.scenario_ids,
            "rows": {
                name: sorted(getattr(self, name), key=lambda row: str(row.get("id", "")))
                for name in self.counts
            },
        }
        encoded = json.dumps(payload, default=_json_default, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def validate(self) -> None:
        """Fail before insertion if a generated business invariant is broken."""

        expected = {
            "customers": 1_000,
            "products": 2_000,
            "orders": 10_000,
            "order_items": 25_000,
            "shipments": 9_200,
            "delivery_slots": 180,
            "refunds": 800,
            "returns": 600,
            "return_items": 900,
            "support_tickets": 500,
            "idempotency_records": 0,
            "commerce_events": 0,
        }
        if self.counts != expected:
            raise ValueError(f"seed counts do not match canonical dataset: {self.counts}")
        for field in self.counts:
            ids = [row.get("id") for row in getattr(self, field) if "id" in row]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate IDs in {field}")
        if len({row["email"] for row in self.customers}) != len(self.customers):
            raise ValueError("customer emails are not unique")
        if len({row["sku"] for row in self.products}) != len(self.products):
            raise ValueError("product SKUs are not unique")
        if len({row["tracking_number"] for row in self.shipments}) != len(self.shipments):
            raise ValueError("tracking numbers are not unique")

        customer_ids = {row["id"] for row in self.customers}
        product_ids = {row["id"] for row in self.products}
        order_ids = {row["id"] for row in self.orders}
        item_ids = {row["id"] for row in self.order_items}
        slot_ids = {row["id"] for row in self.delivery_slots}
        items_by_order: dict[UUID, list[Row]] = {}
        for item in self.order_items:
            if item["order_id"] not in order_ids or item["product_id"] not in product_ids:
                raise ValueError("order item foreign key is not generated")
            items_by_order.setdefault(item["order_id"], []).append(item)
            if item["quantity"] <= 0 or item["unit_price"] < 0:
                raise ValueError("order item quantity or price is invalid")
        for order in self.orders:
            items = items_by_order.get(order["id"], [])
            if not items:
                raise ValueError("every order must have an item")
            total = sum((item["unit_price"] * item["quantity"] for item in items), Decimal("0.00"))
            if order["total"] != total:
                raise ValueError(f"order total mismatch for {order['id']}")
            if order["customer_id"] not in customer_ids:
                raise ValueError("order customer foreign key is not generated")

        order_by_id = {row["id"]: row for row in self.orders}
        shipment_by_order = {row["order_id"]: row for row in self.shipments}
        if len(shipment_by_order) != len(self.shipments):
            raise ValueError("more than one shipment exists for an order")
        for order in self.orders:
            shipment = shipment_by_order.get(order["id"])
            if order["status"] == "pending" and shipment is not None:
                raise ValueError("pending orders cannot have shipments")
            if order["status"] != "pending" and shipment is None:
                raise ValueError("non-pending orders require shipments")
            if shipment is None:
                continue
            allowed = {
                "confirmed": {"pending", "label_created"},
                "processing": {"label_created"},
                "shipped": {"in_transit", "out_for_delivery"},
                "delivered": {"delivered"},
                "cancelled": {"cancelled"},
            }[order["status"]]
            if shipment["status"] not in allowed:
                raise ValueError("shipment state is incompatible with order state")
            if shipment["status"] == "delivered" and shipment["delivered_at"] is None:
                raise ValueError("delivered shipment is missing delivered_at")
            if shipment["status"] != "delivered" and shipment["delivered_at"] is not None:
                raise ValueError("non-delivered shipment has delivered_at")
            if (
                shipment["delivery_slot_id"] is not None
                and shipment["delivery_slot_id"] not in slot_ids
            ):
                raise ValueError("shipment slot foreign key is not generated")

        for refund in self.refunds:
            if refund["order_id"] not in order_ids or refund["amount"] <= 0:
                raise ValueError("invalid refund")
            if refund["amount"] > order_by_id[refund["order_id"]]["total"]:
                raise ValueError("refund exceeds order total")
            expected_manual = refund["amount"] > Decimal("500.00")
            if refund["requires_manual_approval"] is not expected_manual:
                raise ValueError("refund manual-approval threshold invariant failed")
            if refund["status"] == "pending_manual_approval" and not expected_manual:
                raise ValueError("pending manual-approval refund must exceed $500")
        returns_by_id = {row["id"]: row for row in self.returns}
        return_item_keys: set[tuple[UUID, UUID]] = set()
        for item in self.return_items:
            return_item_key = (item["return_id"], item["order_item_id"])
            if return_item_key in return_item_keys or item["quantity"] <= 0:
                raise ValueError("duplicate or invalid return item")
            return_item_keys.add(return_item_key)
            if item["return_id"] not in returns_by_id or item["order_item_id"] not in item_ids:
                raise ValueError("return item foreign key is not generated")
            order_item = next(row for row in self.order_items if row["id"] == item["order_item_id"])
            if returns_by_id[item["return_id"]]["order_id"] != order_item["order_id"]:
                raise ValueError("return item belongs to another order")
            if item["quantity"] > order_item["quantity"]:
                raise ValueError("return quantity exceeds ordered quantity")
        for ticket in self.support_tickets:
            if ticket["customer_id"] not in customer_ids:
                raise ValueError("ticket customer foreign key is not generated")
            if ticket["order_id"] is not None and ticket["order_id"] not in order_ids:
                raise ValueError("ticket order foreign key is not generated")
            if (
                ticket["order_id"] is not None
                and ticket["customer_id"] != order_by_id[ticket["order_id"]]["customer_id"]
            ):
                raise ValueError("ticket customer does not match order customer")
        for slot in self.delivery_slots:
            if slot["reserved_count"] < 0 or slot["reserved_count"] > slot["capacity"]:
                raise ValueError("delivery slot capacity invariant failed")
        assigned = Counter(
            row["delivery_slot_id"] for row in self.shipments if row["delivery_slot_id"] is not None
        )
        for slot in self.delivery_slots:
            if slot["reserved_count"] != assigned[slot["id"]]:
                raise ValueError("delivery slot reserved count mismatch")

        for protected_key in PROTECTED_ORDER_SCENARIOS:
            order_id = self.scenario_ids[protected_key]
            if any(row["order_id"] == order_id for row in self.refunds + self.returns):
                raise ValueError("protected refund scenario has a seeded refund or return")


def _json_default(value: Any) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"unsupported fingerprint value: {type(value)!r}")


def _status_values(counts: dict[str, int], rng: random.Random) -> list[str]:
    values = [status for status, count in counts.items() for _ in range(count)]
    rng.shuffle(values)
    return values


def _customer_rows(config: SeedConfig) -> list[Row]:
    en = _faker("en_US", config.seed, "customers-en")
    ar = _faker("ar_EG", config.seed, "customers-ar")
    rows: list[Row] = []
    for index in range(1_000):
        language = "en" if index < 500 else "ar" if index < 800 else "ar-EG"
        customer_id = (
            _scenario(config, "customer_primary")
            if index == 0
            else _scenario(config, "customer_other")
            if index == 1
            else _uuid(config.seed, "customer", index)
        )
        rows.append(
            {
                "id": customer_id,
                "name": (en if language == "en" else ar).name(),
                "email": f"customer{index + 1:04d}@example.test",
                "language": language,
                "created_at": config.anchor - timedelta(days=index % 365),
            }
        )
    return rows


def _product_rows(config: SeedConfig) -> list[Row]:
    brands = ("Asterion", "Lumera", "Novexa", "Kavora", "Tessera", "Oridian")
    categories = ("EchoHub", "PixelDock", "HomeNode", "SignalBand", "VoltKey", "MeshPod")
    scenario_indices = {
        "product_out_of_stock": 0,
        "product_low_stock": 100,
        "product_standard_stock": 300,
        "product_499_99": 301,
        "product_500_00": 302,
        "product_501_00": 303,
    }
    by_index = {index: name for name, index in scenario_indices.items()}
    special_prices = {
        "product_499_99": Decimal("499.99"),
        "product_500_00": Decimal("500.00"),
        "product_501_00": Decimal("501.00"),
    }
    rows: list[Row] = []
    for index in range(2_000):
        scenario = by_index.get(index)
        if index < 100:
            stock = 0
        elif index < 300:
            stock = 1 + ((index - 100) % 5)
        else:
            stock = 6 + ((index - 300) * 37 % 245)
        if scenario == "product_low_stock":
            stock = 1
        elif scenario in {
            "product_standard_stock",
            "product_499_99",
            "product_500_00",
            "product_501_00",
        }:
            stock = 100
        price = (
            special_prices[scenario]
            if scenario is not None and scenario in special_prices
            else (Decimal("9.99") + Decimal((index * 17) % 49_000) / 100).quantize(Decimal("0.01"))
        )
        product_id = (
            _scenario(config, scenario) if scenario else _uuid(config.seed, "product", index)
        )
        rows.append(
            {
                "id": product_id,
                "sku": f"NC-{index + 1:04d}-{(index * 7919) % 100_000:05d}",
                "name": f"{brands[index % len(brands)]} {categories[(index // len(brands)) % len(categories)]} {index + 1:04d}",
                "description": "Fictional NovaCommerce electronics and home technology product.",
                "price": price,
                "stock": stock,
                "active": True,
                "created_at": config.anchor - timedelta(days=index % 365),
                "updated_at": config.anchor - timedelta(days=index % 365),
            }
        )
    return rows


def _order_rows(
    config: SeedConfig, customers: list[Row], products: list[Row]
) -> tuple[list[Row], list[Row]]:
    primary = _scenario(config, "customer_primary")
    other = _scenario(config, "customer_other")
    scenario_customer = {
        0: primary,
        1: primary,
        2: primary,
        3: primary,
        4: primary,
        10: other,
        20: primary,
        24: primary,
        28: primary,
    }
    scenario_status = {
        0: "confirmed",
        1: "shipped",
        2: "delivered",
        3: "delivered",
        4: "delivered",
        10: "confirmed",
        20: "delivered",
        24: "delivered",
        28: "delivered",
    }
    scenario_products = {
        20: [301],
        24: [302],
        28: [303],
        0: [300, 100],
        1: [300, 100],
        2: [300, 101, 102],
        3: [300, 103],
        4: [300, 104, 105],
        10: [300, 100, 106],
    }
    remaining_counts = Counter(ORDER_STATUS_COUNTS)
    remaining_counts.subtract(Counter(scenario_status.values()))
    remaining_statuses = _status_values(
        {status: remaining_counts[status] for status in ORDER_STATUS_COUNTS},
        random.Random(_derived_seed(config.seed, "order-statuses")),
    )
    status_values: list[str] = []
    remaining_index = 0
    for index in range(10_000):
        if index in scenario_status:
            status_values.append(scenario_status[index])
        else:
            status_values.append(remaining_statuses[remaining_index])
            remaining_index += 1
    product_by_index = dict(enumerate(products))
    orders: list[Row] = []
    items: list[Row] = []
    for index in range(10_000):
        order_id = (
            _scenario(config, "order_cancellable")
            if index == 0
            else _scenario(config, "order_already_shipped")
            if index == 1
            else _scenario(config, "order_delivered_29d")
            if index == 2
            else _scenario(config, "order_delivered_30d")
            if index == 3
            else _scenario(config, "order_delivered_31d")
            if index == 4
            else _scenario(config, "order_other_customer")
            if index == 10
            else _scenario(config, "order_refund_499_99")
            if index == 20
            else _scenario(config, "order_refund_500_00")
            if index == 24
            else _scenario(config, "order_refund_501_00")
            if index == 28
            else _uuid(config.seed, "order", index)
        )
        customer_id = scenario_customer.get(index, customers[index // 10]["id"])
        order_status = status_values[index]
        created_at = config.anchor - timedelta(days=(index * 7) % 365, minutes=(index * 13) % 1_440)
        line_count = 1 + index % 4
        selected = scenario_products.get(index)
        if selected is None:
            start = (index * 37 + 11) % len(products)
            selected = [(start + line) % len(products) for line in range(line_count)]
        elif len(selected) < line_count:
            selected = (
                selected
                + [candidate for candidate in range(len(products)) if candidate not in selected][
                    : line_count - len(selected)
                ]
            )
        else:
            selected = selected[:line_count]
        rng = random.Random(_derived_seed(config.seed, f"order-lines-{index}"))
        order_items: list[Row] = []
        for line_index, product_index in enumerate(selected):
            product = product_by_index[product_index]
            quantity = 1 + rng.randrange(3)
            item_id = _uuid(config.seed, "order_item", index * 4 + line_index)
            order_items.append(
                {
                    "id": item_id,
                    "order_id": order_id,
                    "product_id": product["id"],
                    "quantity": quantity,
                    "unit_price": product["price"],
                }
            )
        total = sum(
            (item["unit_price"] * item["quantity"] for item in order_items), Decimal("0.00")
        )
        if index in (20, 24, 28):
            total = {20: Decimal("499.99"), 24: Decimal("500.00"), 28: Decimal("501.00")}[index]
            item = order_items[0]
            item["quantity"] = 1
            item["unit_price"] = total
        cancelled_at = created_at + timedelta(hours=1) if order_status == "cancelled" else None
        orders.append(
            {
                "id": order_id,
                "customer_id": customer_id,
                "status": order_status,
                "total": total,
                "created_at": created_at,
                "updated_at": created_at,
                "cancelled_at": cancelled_at,
            }
        )
        items.extend(order_items)
    return orders, items


def _slot_rows(config: SeedConfig) -> list[Row]:
    special = {"slot_available": 0, "slot_one_remaining": 1, "slot_full": 2}
    rows: list[Row] = []
    for day_index in range(30):
        service_date = config.as_of + timedelta(days=day_index + 1)
        for window_index, (start_hour, end_hour) in enumerate(WINDOWS):
            index = day_index * 6 + window_index
            name = next((key for key, value in special.items() if value == index), None)
            rows.append(
                {
                    "id": _scenario(config, name)
                    if name
                    else _uuid(config.seed, "delivery_slot", index),
                    "service_date": service_date,
                    "window_start": time(start_hour, 0, tzinfo=UTC),
                    "window_end": time(end_hour, 0, tzinfo=UTC),
                    "capacity": 20,
                    "reserved_count": 0,
                }
            )
    return rows


def _shipments(config: SeedConfig, orders: list[Row], slots: list[Row]) -> list[Row]:
    targets = [slots[0]["id"]] * 5 + [slots[1]["id"]] * 19 + [slots[2]["id"]] * 20
    shipments: list[Row] = []
    delivered_count = 0
    for index, order in enumerate(orders):
        if order["status"] == "pending":
            continue
        status = {
            "confirmed": "label_created",
            "processing": "label_created",
            "shipped": "in_transit",
            "delivered": "delivered",
            "cancelled": "cancelled",
        }[order["status"]]
        if index == 1:
            status = "in_transit"
        delivered_at = None
        if status == "delivered":
            delivered_at = {
                2: config.anchor - timedelta(days=29),
                3: config.anchor - timedelta(days=30),
                4: config.anchor - timedelta(days=31),
            }.get(index, config.anchor - timedelta(days=1 + index % 90, hours=index % 12))
        slot_id = None
        if status == "delivered" and delivered_count < len(targets):
            slot_id = targets[delivered_count]
            delivered_count += 1
        shipments.append(
            {
                "id": _uuid(config.seed, "shipment", index),
                "order_id": order["id"],
                "carrier": "NovaParcel",
                "tracking_number": f"NC-TRK-{index + 1:06d}",
                "status": status,
                "estimated_delivery": delivered_at or config.anchor + timedelta(days=2 + index % 5),
                "delivered_at": delivered_at,
                "delivery_slot_id": slot_id,
            }
        )
    assigned = Counter(
        row["delivery_slot_id"] for row in shipments if row["delivery_slot_id"] is not None
    )
    for slot in slots:
        slot["reserved_count"] = assigned[slot["id"]]
    return shipments


def _refunds(config: SeedConfig, orders: list[Row]) -> list[Row]:
    protected = {_scenario(config, key) for key in PROTECTED_ORDER_SCENARIOS}
    candidates = [
        order for order in orders if order["status"] == "delivered" and order["id"] not in protected
    ]
    statuses = _status_values(
        REFUND_STATUS_COUNTS, random.Random(_derived_seed(config.seed, "refund-statuses"))
    )
    manual_orders = [order for order in candidates if order["total"] > Decimal("500.00")][:200]
    if len(manual_orders) != 200:
        raise ValueError("canonical refund dataset lacks enough orders above $500")
    remaining_orders = [order for order in candidates if order not in manual_orders][:600]
    manual_index = 0
    remaining_index = 0
    rows: list[Row] = []
    for index, status in enumerate(statuses):
        is_manual = status == "pending_manual_approval"
        order = manual_orders[manual_index] if is_manual else remaining_orders[remaining_index]
        if is_manual:
            manual_index += 1
        else:
            remaining_index += 1
        amount = Decimal("500.01") if is_manual else Decimal("1.00")
        rows.append(
            {
                "id": _uuid(config.seed, "refund", index),
                "order_id": order["id"],
                "amount": amount,
                "status": status,
                "reason": "Deterministic development refund scenario.",
                "requires_manual_approval": amount > Decimal("500.00"),
                "created_at": config.anchor - timedelta(days=index % 30),
            }
        )
    return rows


def _returns(
    config: SeedConfig, orders: list[Row], items: list[Row]
) -> tuple[list[Row], list[Row]]:
    protected = {_scenario(config, key) for key in PROTECTED_ORDER_SCENARIOS}
    order_items: dict[UUID, list[Row]] = {}
    for item in items:
        order_items.setdefault(item["order_id"], []).append(item)
    candidates = [order for order in orders if order["id"] not in protected]
    selected = [order for order in candidates if len(order_items[order["id"]]) >= 2][:300]
    selected.extend(
        order
        for order in candidates
        if len(order_items[order["id"]]) == 1 and order not in selected[:300]
    )
    selected = selected[:600]
    statuses = _status_values(
        RETURN_STATUS_COUNTS, random.Random(_derived_seed(config.seed, "return-statuses"))
    )
    returns: list[Row] = []
    return_items: list[Row] = []
    for index, order in enumerate(selected):
        return_id = _uuid(config.seed, "return", index)
        returns.append(
            {
                "id": return_id,
                "order_id": order["id"],
                "reason": "Deterministic development return scenario.",
                "status": statuses[index],
                "created_at": config.anchor - timedelta(days=index % 30),
                "updated_at": config.anchor - timedelta(days=index % 30),
            }
        )
        for line_index, order_item in enumerate(
            order_items[order["id"]][: 2 if index < 300 else 1]
        ):
            return_items.append(
                {
                    "id": _uuid(config.seed, "return_item", index * 2 + line_index),
                    "return_id": return_id,
                    "order_item_id": order_item["id"],
                    "quantity": 1,
                }
            )
    return returns, return_items


def _tickets(config: SeedConfig, orders: list[Row], customers: list[Row]) -> list[Row]:
    statuses = _status_values(
        TICKET_STATUS_COUNTS, random.Random(_derived_seed(config.seed, "ticket-statuses"))
    )
    rows: list[Row] = []
    for index in range(500):
        order = orders[index + 100] if index < 350 else None
        customer_id = (
            order["customer_id"] if order else customers[(index + 350) % len(customers)]["id"]
        )
        rows.append(
            {
                "id": _uuid(config.seed, "support_ticket", index),
                "customer_id": customer_id,
                "order_id": order["id"] if order else None,
                "subject": f"Seeded support ticket {index + 1:04d}",
                "description": "Deterministic development support ticket.",
                "status": statuses[index],
                "created_at": config.anchor - timedelta(days=index % 30),
                "updated_at": config.anchor - timedelta(days=index % 30),
            }
        )
    return rows


def generate_dataset(config: SeedConfig) -> SeedDataset:
    """Build, validate, and return the canonical dataset without database access."""

    customers = _customer_rows(config)
    products = _product_rows(config)
    orders, order_items = _order_rows(config, customers, products)
    delivery_slots = _slot_rows(config)
    shipments = _shipments(config, orders, delivery_slots)
    refunds = _refunds(config, orders)
    returns, return_items = _returns(config, orders, order_items)
    support_tickets = _tickets(config, orders, customers)
    scenario_ids = {scenario.value: scenario_uuid(config, scenario) for scenario in SeedScenario}
    dataset = SeedDataset(
        config.seed,
        config.as_of,
        customers,
        products,
        orders,
        order_items,
        shipments,
        delivery_slots,
        refunds,
        returns,
        return_items,
        support_tickets,
        [],
        [],
        scenario_ids,
    )
    dataset.validate()
    return dataset
