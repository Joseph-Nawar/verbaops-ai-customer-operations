"""M6C-only trusted tool context and strict proposal input schemas."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from verbaops.actions.models import ActionType, TicketCategory
from verbaops.auth.context import TrustedContext


class Stage6ToolModel(BaseModel):
    """Strict immutable JSON schemas used by the Stage 6 registry."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MissingTrustedCustomerContextError(RuntimeError):
    """Raised when a customer-scoped tool has no server-bound customer."""


class Stage6ToolExecutionContext(Stage6ToolModel):
    """Authenticated identity and durable trace links excluded from model input."""

    trusted_context: TrustedContext
    conversation_id: UUID
    agent_run_id: UUID
    tool_invocation_id: UUID

    @property
    def customer_id(self) -> UUID:
        """Expose the already-authenticated customer to frozen read handlers."""

        customer_id = self.trusted_context.customer_id
        if customer_id is None:
            raise MissingTrustedCustomerContextError()
        return customer_id


class RescheduleDeliveryToolInput(Stage6ToolModel):
    action_type: Literal[ActionType.RESCHEDULE_DELIVERY] = ActionType.RESCHEDULE_DELIVERY
    order_id: UUID
    delivery_slot_id: UUID


class CancelOrderToolInput(Stage6ToolModel):
    action_type: Literal[ActionType.CANCEL_ORDER] = ActionType.CANCEL_ORDER
    order_id: UUID


class ReturnItemToolInput(Stage6ToolModel):
    order_item_id: UUID
    quantity: int = Field(gt=0, le=99)


class ReturnToolInput(Stage6ToolModel):
    action_type: Literal[ActionType.INITIATE_RETURN] = ActionType.INITIATE_RETURN
    order_id: UUID
    items: tuple[ReturnItemToolInput, ...] = Field(min_length=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def require_distinct_items(self) -> "ReturnToolInput":
        item_ids = [item.order_item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("return item identifiers must be distinct")
        return self


class SupportTicketToolInput(Stage6ToolModel):
    action_type: Literal[ActionType.CREATE_SUPPORT_TICKET] = ActionType.CREATE_SUPPORT_TICKET
    order_id: UUID | None = None
    category: TicketCategory
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]


class RefundToolInput(Stage6ToolModel):
    action_type: Literal[ActionType.REQUEST_REFUND] = ActionType.REQUEST_REFUND
    order_id: UUID
    amount: Annotated[Decimal, Field(gt=0)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class Stage6RiskLevel(StrEnum):
    """Stage 6 audit classification carried by the existing ToolDefinition shape."""

    READ_ONLY = "read_only"
    PROPOSAL = "proposal"
