from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from novacommerce.seed.config import DEFAULT_AS_OF, DEFAULT_SEED, SeedConfig
from novacommerce.seed.generator import generate_dataset
from novacommerce.seed.ids import deterministic_uuid, scenario_uuid
from novacommerce.seed.scenarios import SeedScenario


def test_seed_dependency_is_exactly_pinned() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"Faker==40.36.0"' in pyproject


def test_canonical_defaults_and_utc_anchor() -> None:
    config = SeedConfig()
    assert config.seed == DEFAULT_SEED == 20260821
    assert config.as_of == DEFAULT_AS_OF == date(2026, 8, 21)
    assert config.anchor == datetime(2026, 8, 21, 12, tzinfo=config.utc)


def test_uuidv5_is_stable_seed_scoped_and_not_uuid4() -> None:
    first = deterministic_uuid(20260821, "customer", "customer_primary")
    assert first == deterministic_uuid(20260821, "customer", "customer_primary")
    assert first != deterministic_uuid(20260822, "customer", "customer_primary")
    assert isinstance(first, UUID)
    assert first.version == 5
    assert scenario_uuid(SeedConfig(), SeedScenario.CUSTOMER_PRIMARY) == first


def test_canonical_dataset_counts_and_distributions() -> None:
    dataset = generate_dataset(SeedConfig())
    assert len(dataset.customers) == 1_000
    assert Counter(row["language"] for row in dataset.customers) == {
        "en": 500,
        "ar": 300,
        "ar-EG": 200,
    }
    assert len(dataset.products) == 2_000
    assert Counter(row["stock"] == 0 for row in dataset.products)[True] == 100
    assert sum(1 <= int(row["stock"]) <= 5 for row in dataset.products) == 200
    assert sum(6 <= int(row["stock"]) <= 250 for row in dataset.products) == 1_700
    assert len(dataset.orders) == 10_000
    assert Counter(row["status"] for row in dataset.orders) == {
        "pending": 800,
        "confirmed": 1_200,
        "processing": 1_500,
        "shipped": 1_800,
        "delivered": 4_000,
        "cancelled": 700,
    }
    assert len(dataset.order_items) == 25_000
    assert len(dataset.shipments) == 9_200
    assert len(dataset.delivery_slots) == 180
    assert len(dataset.refunds) == 800
    assert len(dataset.returns) == 600
    assert len(dataset.return_items) == 900
    assert len(dataset.support_tickets) == 500
    assert Counter(row["status"] for row in dataset.refunds) == {
        "approved": 300,
        "pending_manual_approval": 200,
        "rejected": 150,
        "completed": 150,
    }
    assert Counter(row["status"] for row in dataset.returns) == {
        "requested": 200,
        "approved": 150,
        "rejected": 100,
        "received": 75,
        "completed": 75,
    }
    assert Counter(row["status"] for row in dataset.support_tickets) == {
        "open": 250,
        "in_progress": 150,
        "closed": 100,
    }
    assert dataset.idempotency_records == []
    assert dataset.commerce_events == []


def test_guaranteed_scenarios_have_exact_semantics() -> None:
    dataset = generate_dataset(SeedConfig())
    ids = dataset.scenario_ids
    customers = {row["id"]: row for row in dataset.customers}
    orders = {row["id"]: row for row in dataset.orders}
    shipments = {row["order_id"]: row for row in dataset.shipments}
    products = {row["id"]: row for row in dataset.products}
    assert orders[ids["order_cancellable"]]["customer_id"] == ids["customer_primary"]
    assert orders[ids["order_cancellable"]]["status"] == "confirmed"
    assert shipments[ids["order_cancellable"]]["status"] == "label_created"
    assert orders[ids["order_already_shipped"]]["customer_id"] == ids["customer_primary"]
    assert shipments[ids["order_already_shipped"]]["status"] == "in_transit"
    for days, key in (
        (29, "order_delivered_29d"),
        (30, "order_delivered_30d"),
        (31, "order_delivered_31d"),
    ):
        assert orders[ids[key]]["status"] == "delivered"
        assert shipments[ids[key]]["delivered_at"] == SeedConfig().anchor.replace(
            day=SeedConfig().anchor.day
        ) - __import__("datetime").timedelta(days=days)
    assert (
        customers[ids["customer_other"]]["id"] == orders[ids["order_other_customer"]]["customer_id"]
    )
    for amount, key in (
        ("499.99", "order_refund_499_99"),
        ("500.00", "order_refund_500_00"),
        ("501.00", "order_refund_501_00"),
    ):
        assert orders[ids[key]]["total"] == Decimal(amount)
        assert not any(row["order_id"] == ids[key] for row in dataset.refunds)
        assert not any(row["order_id"] == ids[key] for row in dataset.returns)
    assert products[ids["product_499_99"]]["price"] == Decimal("499.99")
    assert products[ids["product_500_00"]]["price"] == Decimal("500.00")
    assert products[ids["product_501_00"]]["price"] == Decimal("501.00")


def test_fingerprint_is_stable_and_sensitive_to_seed_and_as_of() -> None:
    canonical = generate_dataset(SeedConfig())
    assert canonical.fingerprint == generate_dataset(SeedConfig()).fingerprint
    assert canonical.fingerprint != generate_dataset(SeedConfig(seed=20260822)).fingerprint
    assert (
        canonical.fingerprint != generate_dataset(SeedConfig(as_of=date(2026, 8, 22))).fingerprint
    )


def test_all_generated_datetimes_are_aware_utc_and_times_are_time_values() -> None:
    dataset = generate_dataset(SeedConfig())
    for rows in (
        dataset.orders,
        dataset.shipments,
        dataset.refunds,
        dataset.returns,
        dataset.support_tickets,
    ):
        for row in rows:
            for value in row.values():
                if isinstance(value, datetime):
                    assert value.tzinfo is not None
                    assert value.utcoffset() == __import__("datetime").timedelta(0)
    assert all(isinstance(row["window_start"], time) for row in dataset.delivery_slots)
    assert all(isinstance(row["window_end"], time) for row in dataset.delivery_slots)
    assert {row["reserved_count"] for row in dataset.delivery_slots[:3]} == {5, 19, 20}


def test_generation_has_no_implicit_wall_clock_dependency() -> None:
    source = Path("src/novacommerce/seed/generator.py").read_text(encoding="utf-8")
    assert "datetime.now(" not in source
    assert "date.today(" not in source
    assert "random.seed(" not in source


def test_dataset_validation_is_explicit() -> None:
    dataset = generate_dataset(SeedConfig())
    dataset.orders[0]["total"] = Decimal("0.00")
    try:
        dataset.validate()
    except ValueError as error:
        assert "total" in str(error)
    else:
        raise AssertionError("dataset mutation should violate a declared invariant")
