import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from verbaops.actions import models as action_models
from verbaops.actions.fingerprints import fingerprint_proposal
from verbaops.actions.models import (
    ActionType,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnItemProposal,
    ReturnProposal,
    SupportTicketProposal,
    TicketCategory,
)

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
CUSTOMER_ID = UUID("20000000-0000-4000-8000-000000000002")
ORDER_ID = UUID("30000000-0000-4000-8000-000000000003")
SLOT_ID = UUID("40000000-0000-4000-8000-000000000004")


def _fingerprint(**overrides: Any) -> str:
    values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "customer_id": CUSTOMER_ID,
        "action_type": ActionType.RESCHEDULE_DELIVERY,
        "schema_version": "action-proposal-v1",
        "target_ids": (ORDER_ID, SLOT_ID),
        "normalized_payload": {
            "order_id": ORDER_ID,
            "delivery_slot_id": SLOT_ID,
            "category": TicketCategory.DELIVERY,
            "amount": Decimal("500.0"),
            "preflight_at": datetime(2026, 10, 3, 15, 0, tzinfo=timezone(timedelta(hours=3))),
        },
        "material_snapshot": {
            "order_status": "confirmed",
            "current_slot_id": UUID("50000000-0000-4000-8000-000000000005"),
        },
    }
    values.update(overrides)
    return fingerprint_proposal(**values)


def test_fingerprint_is_stable_for_equivalent_normalized_inputs() -> None:
    original = _fingerprint()
    equivalent = _fingerprint(
        target_ids=(SLOT_ID, ORDER_ID),
        normalized_payload={
            "preflight_at": datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
            "amount": Decimal("500.00"),
            "category": "delivery",
            "delivery_slot_id": str(SLOT_ID),
            "order_id": str(ORDER_ID),
        },
        material_snapshot={
            "current_slot_id": "50000000-0000-4000-8000-000000000005",
            "order_status": "confirmed",
        },
    )

    assert equivalent == original
    assert re.fullmatch(r"[0-9a-f]{64}", original)


def test_fingerprint_changes_for_scope_action_schema_payload_or_snapshot() -> None:
    original = _fingerprint()
    changes: tuple[dict[str, Any], ...] = (
        {"tenant_id": UUID("10000000-0000-4000-8000-000000000009")},
        {"customer_id": UUID("20000000-0000-4000-8000-000000000009")},
        {"action_type": ActionType.CANCEL_ORDER},
        {"schema_version": "action-proposal-v2"},
        {"normalized_payload": {"order_id": ORDER_ID, "delivery_slot_id": SLOT_ID}},
        {"material_snapshot": {"order_status": "processing"}},
    )

    for change in changes:
        assert _fingerprint(**change) != original


def test_fingerprint_excludes_action_identity_prompts_secrets_and_gate_decisions() -> None:
    payload = {"order_id": ORDER_ID, "delivery_slot_id": SLOT_ID}
    original = _fingerprint(normalized_payload=payload)
    excluded = _fingerprint(
        normalized_payload={
            **payload,
            "action_request_id": UUID("60000000-0000-4000-8000-000000000006"),
            "prompt": "private instruction",
            "secret": "credential",
            "approval_required": True,
            "confirmation_required": True,
        }
    )

    assert excluded == original


def test_refund_fingerprint_uses_fixed_scale_model_serialization() -> None:
    def refund_fingerprint(amount: Decimal) -> str:
        proposal = RefundProposal(order_id=ORDER_ID, amount=amount, reason="Duplicate charge")
        return fingerprint_proposal(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
            action_type=ActionType.REQUEST_REFUND,
            schema_version="action-proposal-v1",
            target_ids=(ORDER_ID,),
            normalized_payload=proposal.model_dump(mode="json"),
            material_snapshot={"order_status": "confirmed"},
        )

    assert refund_fingerprint(Decimal("500.0")) == refund_fingerprint(Decimal("500.00"))


def test_material_changes_change_fingerprint_with_stable_business_targets() -> None:
    other_order_item_id = UUID("70000000-0000-4000-8000-000000000007")
    other_slot_id = UUID("80000000-0000-4000-8000-000000000008")
    material_pairs = (
        (
            RescheduleDeliveryProposal(order_id=ORDER_ID, delivery_slot_id=SLOT_ID),
            RescheduleDeliveryProposal(order_id=ORDER_ID, delivery_slot_id=other_slot_id),
        ),
        (
            ReturnProposal(
                order_id=ORDER_ID,
                items=(ReturnItemProposal(order_item_id=SLOT_ID, quantity=1),),
                reason="Wrong size",
            ),
            ReturnProposal(
                order_id=ORDER_ID,
                items=(ReturnItemProposal(order_item_id=other_order_item_id, quantity=1),),
                reason="Wrong size",
            ),
        ),
        (
            RefundProposal(order_id=ORDER_ID, amount=Decimal("10.00"), reason="Duplicate"),
            RefundProposal(order_id=ORDER_ID, amount=Decimal("20.00"), reason="Duplicate"),
        ),
        (
            SupportTicketProposal(
                order_id=ORDER_ID,
                category=TicketCategory.ORDER,
                subject="Question",
                description="First description",
            ),
            SupportTicketProposal(
                order_id=ORDER_ID,
                category=TicketCategory.DELIVERY,
                subject="Updated question",
                description="Corrected description",
            ),
        ),
    )

    for first, corrected in material_pairs:
        first_targets = action_models.proposal_target_ids(first)
        corrected_targets = action_models.proposal_target_ids(corrected)
        assert first_targets == corrected_targets == (ORDER_ID,)
        first_fingerprint = fingerprint_proposal(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
            action_type=first.action_type,
            schema_version="action-proposal-v1",
            target_ids=first_targets,
            normalized_payload=first.model_dump(mode="json"),
            material_snapshot={"order_status": "confirmed"},
        )
        corrected_fingerprint = fingerprint_proposal(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
            action_type=corrected.action_type,
            schema_version="action-proposal-v1",
            target_ids=corrected_targets,
            normalized_payload=corrected.model_dump(mode="json"),
            material_snapshot={"order_status": "confirmed"},
        )
        assert corrected_fingerprint != first_fingerprint
