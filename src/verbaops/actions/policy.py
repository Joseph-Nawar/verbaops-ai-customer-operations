"""Pure deterministic gates for the initial Stage 6 action policy."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field, model_validator

from verbaops.actions.models import (
    ActionModel,
    ActionProposal,
    CancelOrderProposal,
    CommerceSnapshot,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnProposal,
    SupportTicketProposal,
)
from verbaops.auth.context import Role, TrustedContext
from verbaops.commerce.models import OrderStatus, ShipmentStatus

_REASON_CODE = Annotated[str, Field(min_length=1, max_length=128)]
_POLICY_VERSION = Annotated[str, Field(min_length=1, max_length=128)]
_REFUND_APPROVAL_THRESHOLD = Decimal("500.00")


class PolicyDecision(ActionModel):
    """Immutable policy outcome and the gates required for an allowed proposal."""

    allowed: bool
    reason_code: _REASON_CODE
    confirmation_required: bool
    approval_required: bool
    policy_version: _POLICY_VERSION

    @model_validator(mode="after")
    def validate_gate_consistency(self) -> "PolicyDecision":
        if not self.allowed and (self.confirmation_required or self.approval_required):
            raise ValueError("denied proposals cannot carry actionable gates")
        if self.approval_required and not self.confirmation_required:
            raise ValueError("supervisor approval cannot replace customer confirmation")
        return self


def _denied(policy_version: str, reason_code: str) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        reason_code=reason_code,
        confirmation_required=False,
        approval_required=False,
        policy_version=policy_version,
    )


def _allowed(policy_version: str, *, approval_required: bool = False) -> PolicyDecision:
    return PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=approval_required,
        policy_version=policy_version,
    )


def _evaluate_reschedule(policy_version: str) -> PolicyDecision:
    return _allowed(policy_version)


def _evaluate_cancellation(snapshot: CommerceSnapshot, policy_version: str) -> PolicyDecision:
    approval_required = (
        snapshot.order_status is OrderStatus.PROCESSING
        or snapshot.shipment_status is ShipmentStatus.LABEL_CREATED
    )
    return _allowed(policy_version, approval_required=approval_required)


def _evaluate_return(policy_version: str) -> PolicyDecision:
    return _allowed(policy_version)


def _evaluate_support_ticket(policy_version: str) -> PolicyDecision:
    return _allowed(policy_version)


def _evaluate_refund(proposal: RefundProposal, policy_version: str) -> PolicyDecision:
    return _allowed(
        policy_version,
        approval_required=proposal.amount > _REFUND_APPROVAL_THRESHOLD,
    )


def evaluate_action_policy(
    trusted_context: TrustedContext,
    proposal: ActionProposal,
    commerce_snapshot: CommerceSnapshot,
    canonical_currency: str | None,
    policy_version: str,
) -> PolicyDecision:
    """Evaluate trusted scope, current Commerce facts, and the frozen action gates."""

    if not policy_version.strip():
        raise ValueError("policy version must be non-empty")

    roles = trusted_context.roles
    can_propose = Role.CUSTOMER in roles or Role.SUPPORT_AGENT in roles
    if not can_propose:
        return _denied(policy_version, "proposal_role_not_allowed")
    if trusted_context.customer_id is None:
        return _denied(policy_version, "customer_binding_required")
    if trusted_context.customer_id != commerce_snapshot.customer_id:
        return _denied(policy_version, "customer_scope_mismatch")

    proposal_order_id = getattr(proposal, "order_id", None)
    if proposal_order_id is not None and proposal_order_id != commerce_snapshot.order_id:
        return _denied(policy_version, "proposal_resource_mismatch")
    if not commerce_snapshot.fresh:
        return _denied(policy_version, "stale_snapshot")
    if not commerce_snapshot.eligible:
        return _denied(policy_version, "commerce_ineligible")
    if isinstance(proposal, RefundProposal) and (
        canonical_currency is None or not canonical_currency.strip()
    ):
        return _denied(policy_version, "canonical_currency_unavailable")

    if isinstance(proposal, RescheduleDeliveryProposal):
        return _evaluate_reschedule(policy_version)
    if isinstance(proposal, CancelOrderProposal):
        return _evaluate_cancellation(commerce_snapshot, policy_version)
    if isinstance(proposal, ReturnProposal):
        return _evaluate_return(policy_version)
    if isinstance(proposal, SupportTicketProposal):
        return _evaluate_support_ticket(policy_version)
    if isinstance(proposal, RefundProposal):
        return _evaluate_refund(proposal, policy_version)
    raise TypeError(f"unsupported action proposal: {type(proposal).__name__}")
