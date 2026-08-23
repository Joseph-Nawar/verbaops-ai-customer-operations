"""Safety and determinism tests for the setup-only acceptance overlay."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from scripts.apply_commerce_acceptance_overlay import (
    build_overlay_rows,
    ensure_overlay_absent,
)

MANIFEST = json.loads(
    (Path(__file__).parent / "acceptance" / "fixtures" / "novacommerce-scenarios.json").read_text(
        encoding="utf-8"
    )
)


def test_overlay_rows_are_time_relative_and_use_only_overlay_entity_ids() -> None:
    as_of = datetime(2031, 4, 5, 6, 7, 8, tzinfo=UTC)
    rows = build_overlay_rows(MANIFEST, as_of)
    overlay_ids = {UUID(value) for value in MANIFEST["overlay_ids"].values()}
    scenario_ids = {UUID(value) for value in MANIFEST["scenario_ids"].values()}

    created_ids = {row["id"] for table_rows in rows.values() for row in table_rows if "id" in row}
    assert created_ids <= overlay_ids
    assert not created_ids & scenario_ids

    primary = UUID(MANIFEST["scenario_ids"]["customer_primary"])
    assert {row["customer_id"] for row in rows["orders"]} == {primary}
    assert {row["product_id"] for row in rows["order_items"]} == {
        UUID(MANIFEST["overlay_ids"]["overlay_product"])
    }
    assert {row["id"] for row in rows["delivery_slots"]} == {
        UUID(MANIFEST["overlay_ids"][name]) for name in ("slot_x", "slot_y")
    }
    assert rows["delivery_slots"][0]["service_date"] == date(2031, 5, 15)
    assert rows["delivery_slots"][1]["service_date"] == date(2031, 5, 16)
    source = (
        Path(__file__).parents[1] / "scripts" / "apply_commerce_acceptance_overlay.py"
    ).read_text(encoding="utf-8")
    assert "update(" not in source
    assert "delete(" not in source


def test_overlay_rerun_fails_clearly_when_existing() -> None:
    with pytest.raises(ValueError, match="acceptance overlay already exists"):
        ensure_overlay_absent(UUID("5bd5847c-96a5-5403-92d8-6aaa9efa6f3a"))
