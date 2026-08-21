"""Static contracts for the isolated NovaCommerce Alembic environment."""

from pathlib import Path

from novacommerce.db import models as _models
from novacommerce.db.base import Base


def test_commerce_alembic_configuration_is_separate_and_secret_free() -> None:
    config = Path("alembic-commerce.ini").read_text(encoding="utf-8")
    assert "script_location = commerce_migrations" in config
    assert "sqlalchemy.url" not in config
    assert "password" not in config.lower()


def test_commerce_env_targets_novacommerce_metadata() -> None:
    env = Path("commerce_migrations/env.py").read_text(encoding="utf-8")
    assert "target_metadata = Base.metadata" in env
    assert "novacommerce.config.settings" in env
    assert "verbaops" not in env.lower()


def test_initial_commerce_revision_is_reversible_and_uses_expected_schema() -> None:
    migration = Path("commerce_migrations/versions/0001_create_commerce_schema.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0001_create_commerce_schema"' in migration
    assert "def upgrade" in migration
    assert "def downgrade" in migration
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
    assert _models.Customer.__tablename__ == "customers"


def test_existing_verbaops_migration_tree_is_unchanged_by_commerce_migrations() -> None:
    assert not any(Path("migrations/versions").glob("*commerce*"))
