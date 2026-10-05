"""Durable evidence construction for high-value refund writes."""

from verbaops.actions.transitions import ActionRequestRecord
from verbaops.commerce.models import RefundApprovalReference


class InvalidRefundApprovalEvidence(ValueError):
    """A durable high-value refund record cannot prove supervisor approval."""


def refund_approval_reference(
    record: ActionRequestRecord,
) -> RefundApprovalReference | None:
    """Build the Commerce evidence only from the durable action approval fields."""

    if not record.approval_required:
        return None
    if (
        record.supervisor_approval_decision != "approved"
        or record.supervisor_approval_actor_id is None
        or record.supervisor_approval_fingerprint != record.proposal_fingerprint
    ):
        raise InvalidRefundApprovalEvidence("durable supervisor approval evidence is invalid")
    return RefundApprovalReference(
        action_request_id=record.id,
        proposal_fingerprint=record.proposal_fingerprint,
    )
