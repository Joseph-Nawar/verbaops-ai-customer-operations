"""Tests for the explicit five-tool READ_ONLY registry."""

import pytest

from verbaops.commerce.models import ProductSearchResponse
from verbaops.tools.commerce_reads import get_order_status
from verbaops.tools.models import (
    GetOrderStatusInput,
    RetryPolicy,
    RiskLevel,
    ToolDefinition,
)
from verbaops.tools.registry import (
    DuplicateToolError,
    ToolRegistry,
    UnknownToolError,
    build_commerce_read_registry,
)


def test_production_registry_exposes_exactly_five_read_only_tools() -> None:
    registry = build_commerce_read_registry()

    assert registry.names == (
        "get_order_status",
        "get_shipment_status",
        "get_refund_status",
        "search_products",
        "list_delivery_slots",
    )
    assert all(definition.risk_level is RiskLevel.READ_ONLY for definition in registry)
    assert all(definition.retry_policy.max_attempts == 2 for definition in registry)


def test_registry_rejects_duplicate_names_and_unknown_lookup() -> None:
    definition = ToolDefinition(
        name="duplicate",
        description="test",
        input_model=GetOrderStatusInput,
        output_model=ProductSearchResponse,
        risk_level=RiskLevel.READ_ONLY,
        timeout_seconds=5.0,
        retry_policy=RetryPolicy.commerce_read(),
        handler=get_order_status,
    )

    with pytest.raises(DuplicateToolError):
        ToolRegistry((definition, definition))
    with pytest.raises(UnknownToolError):
        build_commerce_read_registry().get("unknown")


def test_registry_definitions_are_immutable_and_have_required_fields() -> None:
    definition = build_commerce_read_registry().get("get_order_status")

    assert {
        "name",
        "description",
        "input_model",
        "output_model",
        "risk_level",
        "timeout_seconds",
        "retry_policy",
        "handler",
    } == set(definition.__dataclass_fields__)
    with pytest.raises((AttributeError, TypeError)):
        definition.name = "changed"  # type: ignore[misc]


def test_registry_model_schemas_contain_no_trusted_identity_or_credential_fields() -> None:
    forbidden = {"tenant_id", "principal_id", "customer_id", "roles", "service_token"}

    for definition in build_commerce_read_registry():
        fields = set(definition.input_model.model_json_schema().get("properties", {}))
        assert fields.isdisjoint(forbidden)


def test_no_write_or_mutation_name_is_in_production_registry() -> None:
    names = set(build_commerce_read_registry().names)
    assert not any(
        any(
            word in name for word in ("write", "create", "cancel", "reschedule", "return", "ticket")
        )
        for name in names
    )


def test_tool_definition_handler_is_explicitly_typed() -> None:
    assert callable(build_commerce_read_registry().get("search_products").handler)
