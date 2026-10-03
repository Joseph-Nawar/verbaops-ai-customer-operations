"""Explicit M6C allowlist layered beside the frozen M5D registry contract."""

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, cast

from verbaops.actions.models import ActionRequestSummary
from verbaops.commerce.client import CommerceClient
from verbaops.tools.models import (
    RetryPolicy,
    RiskLevel,
    ToolDefinition,
)
from verbaops.tools.proposals import build_proposal_handlers
from verbaops.tools.registry import ToolRegistry, build_commerce_read_registry
from verbaops.tools.stage6_commerce_reads import (
    get_order_status,
    get_refund_status,
    get_shipment_status,
    list_delivery_slots,
    search_products,
)
from verbaops.tools.stage6_models import Stage6RiskLevel, Stage6ToolExecutionContext


class Stage6ToolRegistry(ToolRegistry):
    """Strict JSON-boundary executor for the M6C registry."""

    def validate_input(self, name: str, raw_input: Mapping[str, Any]) -> Any:
        """Validate provider-decoded JSON before any durable invocation is created."""

        definition = self.get(name)
        serialized = json.dumps(raw_input, ensure_ascii=False, separators=(",", ":"), default=str)
        return definition.input_model.model_validate_json(serialized)

    async def execute(
        self,
        name: str,
        raw_input: Mapping[str, Any],
        context: object,
        client: CommerceClient,
    ) -> Any:
        definition = self.get(name)
        input_data = self.validate_input(name, raw_input)
        if not isinstance(context, Stage6ToolExecutionContext):
            raise TypeError("Stage 6 tool execution requires authenticated context")
        output = await definition.handler(
            input_data,
            cast(Any, context),
            client,
        )
        return definition.output_model.model_validate(output)


def build_stage6_tool_registry(action_proposal_service: Any) -> Stage6ToolRegistry:
    """Build five existing Commerce reads plus the five explicit proposal tools."""

    stage6_read_handlers = {
        "get_order_status": get_order_status,
        "get_shipment_status": get_shipment_status,
        "get_refund_status": get_refund_status,
        "search_products": search_products,
        "list_delivery_slots": list_delivery_slots,
    }
    definitions = [
        replace(definition, handler=cast(Any, stage6_read_handlers[definition.name]))
        if definition.name in stage6_read_handlers
        else definition
        for definition in build_commerce_read_registry()
    ]
    no_retry = RetryPolicy(
        max_attempts=1,
        retryable_status_codes=(),
        retry_on_timeout=False,
        retry_on_transport=False,
    )
    for name, input_model, description, handler in build_proposal_handlers(action_proposal_service):
        definitions.append(
            ToolDefinition(
                name=name,
                description=description,
                input_model=input_model,
                output_model=ActionRequestSummary,
                risk_level=cast(RiskLevel, Stage6RiskLevel.PROPOSAL),
                timeout_seconds=20.0,
                retry_policy=no_retry,
                handler=handler,
            )
        )
    return Stage6ToolRegistry(definitions)


__all__ = ["Stage6ToolExecutionContext", "Stage6ToolRegistry", "build_stage6_tool_registry"]
