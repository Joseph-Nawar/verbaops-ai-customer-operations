"""Explicit immutable registry for the M3C read-only tools."""

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Any

from verbaops.commerce.client import CommerceClient
from verbaops.tools.models import (
    GetOrderStatusInput,
    GetOrderStatusOutput,
    GetRefundStatusInput,
    GetRefundStatusOutput,
    GetShipmentStatusInput,
    GetShipmentStatusOutput,
    ListDeliverySlotsInput,
    ListDeliverySlotsOutput,
    RetryPolicy,
    RiskLevel,
    SearchProductsInput,
    SearchProductsOutput,
    ToolDefinition,
    ToolExecutionContext,
)


class ToolRegistryError(ValueError):
    """Base error for deterministic registry construction and lookup failures."""


class DuplicateToolError(ToolRegistryError):
    """Raised when a registry contains duplicate names."""


class UnknownToolError(ToolRegistryError):
    """Raised when a caller requests a name outside the explicit allowlist."""


class ToolRegistry:
    """Immutable-by-construction explicit tool definition allowlist."""

    def __init__(self, definitions: Iterable[ToolDefinition]) -> None:
        self._definitions = tuple(definitions)
        by_name: dict[str, ToolDefinition] = {}
        for definition in self._definitions:
            if definition.name in by_name:
                raise DuplicateToolError("duplicate tool name")
            by_name[definition.name] = definition
        self._by_name = MappingProxyType(by_name)

    @property
    def names(self) -> tuple[str, ...]:
        """Return the explicit registry order."""

        return tuple(definition.name for definition in self._definitions)

    def __iter__(self) -> Iterator[ToolDefinition]:
        return iter(self._definitions)

    def get(self, name: str) -> ToolDefinition:
        """Return an allowlisted definition or fail deterministically."""

        try:
            return self._by_name[name]
        except KeyError:
            raise UnknownToolError("unknown tool") from None

    async def execute(
        self,
        name: str,
        raw_input: Mapping[str, Any],
        context: ToolExecutionContext,
        client: CommerceClient,
    ) -> Any:
        """Validate model input, invoke one explicit handler, and validate output."""

        definition = self.get(name)
        input_data = definition.input_model.model_validate(raw_input)
        output = await definition.handler(input_data, context, client)
        return definition.output_model.model_validate(output)


def build_commerce_read_registry() -> ToolRegistry:
    """Build the exact five-tool M3C registry from explicit bindings."""

    from verbaops.tools.commerce_reads import (
        get_order_status,
        get_refund_status,
        get_shipment_status,
        list_delivery_slots,
        search_products,
    )

    retry_policy = RetryPolicy.commerce_read()
    return ToolRegistry(
        (
            ToolDefinition(
                name="get_order_status",
                description="Get the status and total for the trusted customer's order.",
                input_model=GetOrderStatusInput,
                output_model=GetOrderStatusOutput,
                risk_level=RiskLevel.READ_ONLY,
                timeout_seconds=15.0,
                retry_policy=retry_policy,
                handler=get_order_status,
            ),
            ToolDefinition(
                name="get_shipment_status",
                description="Get shipment tracking and delivery status for the trusted customer's order.",
                input_model=GetShipmentStatusInput,
                output_model=GetShipmentStatusOutput,
                risk_level=RiskLevel.READ_ONLY,
                timeout_seconds=15.0,
                retry_policy=retry_policy,
                handler=get_shipment_status,
            ),
            ToolDefinition(
                name="get_refund_status",
                description="Get refund status for the trusted customer's order.",
                input_model=GetRefundStatusInput,
                output_model=GetRefundStatusOutput,
                risk_level=RiskLevel.READ_ONLY,
                timeout_seconds=15.0,
                retry_policy=retry_policy,
                handler=get_refund_status,
            ),
            ToolDefinition(
                name="search_products",
                description="Search the product catalog by a bounded text query.",
                input_model=SearchProductsInput,
                output_model=SearchProductsOutput,
                risk_level=RiskLevel.READ_ONLY,
                timeout_seconds=15.0,
                retry_policy=retry_policy,
                handler=search_products,
            ),
            ToolDefinition(
                name="list_delivery_slots",
                description="List delivery slots in a bounded date range.",
                input_model=ListDeliverySlotsInput,
                output_model=ListDeliverySlotsOutput,
                risk_level=RiskLevel.READ_ONLY,
                timeout_seconds=15.0,
                retry_policy=retry_policy,
                handler=list_delivery_slots,
            ),
        )
    )
