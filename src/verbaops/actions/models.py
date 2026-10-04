"""Typed action proposals and lifecycle values."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from verbaops.commerce.models import OrderStatus, ShipmentStatus

type JSONValue = (
    str
    | int
    | float
    | bool
    | UUID
    | Decimal
    | datetime
    | StrEnum
    | list[JSONValue]
    | tuple[JSONValue, ...]
    | dict[str, JSONValue]
    | None
)


class ActionType(StrEnum):
    """Supported immutable action kinds."""

    RESCHEDULE_DELIVERY = "reschedule_delivery"
    CANCEL_ORDER = "cancel_order"
    INITIATE_RETURN = "initiate_return"
    CREATE_SUPPORT_TICKET = "create_support_ticket"
    REQUEST_REFUND = "request_refund"


class ActionState(StrEnum):
    """The exact Stage 6 action lifecycle states."""

    PROPOSED = "proposed"
    POLICY_DENIED = "policy_denied"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    READY_TO_EXECUTE = "ready_to_execute"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    UNRESOLVED = "unresolved"
    EXPIRED = "expired"


class ActionGate(StrEnum):
    """Human decisions required before a proposal can execute."""

    CUSTOMER_CONFIRMATION = "customer_confirmation"
    SUPERVISOR_APPROVAL = "supervisor_approval"


class TicketCategory(StrEnum):
    """Stable support-ticket category keys from the approved Stage 6 contract."""

    ORDER = "order"
    DELIVERY = "delivery"
    RETURNS_REFUNDS = "returns_refunds"
    PRODUCT = "product"
    WARRANTY = "warranty"
    PAYMENT = "payment"
    ACCOUNT = "account"
    OTHER = "other"


class ActionModel(BaseModel):
    """Strict immutable base for normalized action-domain values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


ReasonText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
SubjectText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
DescriptionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


class RescheduleDeliveryProposal(ActionModel):
    action_type: Literal[ActionType.RESCHEDULE_DELIVERY] = ActionType.RESCHEDULE_DELIVERY
    order_id: UUID
    delivery_slot_id: UUID


class CancelOrderProposal(ActionModel):
    action_type: Literal[ActionType.CANCEL_ORDER] = ActionType.CANCEL_ORDER
    order_id: UUID


class ReturnItemProposal(ActionModel):
    order_item_id: UUID
    quantity: int = Field(gt=0, le=99)


class ReturnProposal(ActionModel):
    action_type: Literal[ActionType.INITIATE_RETURN] = ActionType.INITIATE_RETURN
    order_id: UUID
    items: tuple[ReturnItemProposal, ...] = Field(min_length=1)
    reason: ReasonText

    @model_validator(mode="after")
    def require_distinct_items(self) -> "ReturnProposal":
        item_ids = [item.order_item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("return item identifiers must be distinct")
        return self


class SupportTicketProposal(ActionModel):
    action_type: Literal[ActionType.CREATE_SUPPORT_TICKET] = ActionType.CREATE_SUPPORT_TICKET
    order_id: UUID | None = None
    category: TicketCategory
    subject: SubjectText
    description: DescriptionText


class RefundProposal(ActionModel):
    action_type: Literal[ActionType.REQUEST_REFUND] = ActionType.REQUEST_REFUND
    order_id: UUID
    amount: Decimal = Field(gt=Decimal("0"))
    reason: ReasonText

    @field_validator("amount")
    @classmethod
    def require_cent_precision(cls, value: Decimal) -> Decimal:
        normalized = value.quantize(Decimal("0.01"))
        if normalized != value:
            raise ValueError("refund amount must use at most two decimal places")
        return normalized


type ActionProposal = Annotated[
    RescheduleDeliveryProposal
    | CancelOrderProposal
    | ReturnProposal
    | SupportTicketProposal
    | RefundProposal,
    Field(discriminator="action_type"),
]


def proposal_target_ids(proposal: ActionProposal) -> tuple[UUID, ...]:
    """Return stable business-resource IDs; proposal alternatives remain material data."""

    if isinstance(
        proposal,
        (RescheduleDeliveryProposal, CancelOrderProposal, ReturnProposal, RefundProposal),
    ):
        return (proposal.order_id,)
    if isinstance(proposal, SupportTicketProposal):
        return (proposal.order_id,) if proposal.order_id is not None else ()
    raise TypeError("proposal must be a supported action proposal")


class CommerceSnapshot(ActionModel):
    """Typed, server-fetched facts used by deterministic action policy."""

    customer_id: UUID
    order_id: UUID | None = None
    order_status: OrderStatus | None = None
    shipment_status: ShipmentStatus | None = None
    eligible: bool
    fresh: bool
    observed_at: datetime
    material_values: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def require_timezone_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot observation time must be timezone-aware")
        return value


class ActionRequestSummary(ActionModel):
    """Safe server-owned proposal state returned to the agent and caller."""

    action_request_id: UUID
    action_type: ActionType
    state: ActionState
    proposal_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    safe_summary: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    required_next_actor: Literal["customer", "support_supervisor", "none"]
    reason_code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")]
