"""Fixed customer-only action view, confirmation, withdrawal, and reconciliation routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

from verbaops.actions.decisions import (
    ActionDecisionConflictError,
    ActionDecisionForbiddenError,
    ActionDecisionService,
    ActionFreshnessUnavailableError,
    ActionRequestView,
)
from verbaops.actions.reconciliation import ActionReconciler, ActionReconciliationForbiddenError
from verbaops.actions.transitions import ActionRequestNotFoundError
from verbaops.api.dependencies import (
    get_action_decision_service,
    get_action_reconciler,
    get_trusted_context,
)
from verbaops.api.errors import PublicAPIError
from verbaops.auth.context import TrustedContext

router = APIRouter(prefix="/v1/action-requests", tags=["action-requests"])


class CustomerDecisionRequest(BaseModel):
    """Exact customer fingerprint binding accepted by decision routes."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    proposal_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


ContextDependency = Annotated[TrustedContext, Depends(get_trusted_context)]
DecisionServiceDependency = Annotated[ActionDecisionService, Depends(get_action_decision_service)]
ReconcilerDependency = Annotated[ActionReconciler, Depends(get_action_reconciler)]


@router.get("/{action_request_id}", response_model=ActionRequestView)
async def get_action_request(
    action_request_id: UUID,
    context: ContextDependency,
    service: DecisionServiceDependency,
) -> ActionRequestView:
    try:
        return await service.get_action_request(action_request_id, context)
    except ActionRequestNotFoundError:
        raise _not_found() from None
    except ActionDecisionForbiddenError:
        raise _customer_authority_required() from None
    except ActionFreshnessUnavailableError:
        raise PublicAPIError(
            503, "action_freshness_unavailable", "action facts are unavailable"
        ) from None


@router.post("/{action_request_id}/confirmation", response_model=ActionRequestView)
async def confirm_action_request(
    action_request_id: UUID,
    request: CustomerDecisionRequest,
    context: ContextDependency,
    service: DecisionServiceDependency,
) -> ActionRequestView:
    try:
        return await service.confirm(action_request_id, context, request.proposal_fingerprint)
    except ActionRequestNotFoundError:
        raise _not_found() from None
    except ActionDecisionForbiddenError:
        raise _customer_authority_required() from None
    except ActionDecisionConflictError:
        raise _decision_conflict() from None
    except ActionFreshnessUnavailableError:
        raise PublicAPIError(
            503, "action_freshness_unavailable", "action facts are unavailable"
        ) from None


@router.post("/{action_request_id}/rejection", response_model=ActionRequestView)
async def reject_action_request(
    action_request_id: UUID,
    request: CustomerDecisionRequest,
    context: ContextDependency,
    service: DecisionServiceDependency,
) -> ActionRequestView:
    try:
        return await service.reject(action_request_id, context, request.proposal_fingerprint)
    except ActionRequestNotFoundError:
        raise _not_found() from None
    except ActionDecisionForbiddenError:
        raise _customer_authority_required() from None
    except ActionDecisionConflictError:
        raise _decision_conflict() from None


@router.post("/{action_request_id}/reconciliation", response_model=ActionRequestView)
async def reconcile_action_request(
    action_request_id: UUID,
    http_request: Request,
    context: ContextDependency,
    reconciler: ReconcilerDependency,
    service: DecisionServiceDependency,
) -> ActionRequestView:
    if await http_request.body():
        raise PublicAPIError(422, "request_validation_error", "request validation failed")
    try:
        await reconciler.reconcile(action_request_id, context)
        return await service.get_action_request(action_request_id, context)
    except ActionRequestNotFoundError:
        raise _not_found() from None
    except (ActionDecisionForbiddenError, ActionReconciliationForbiddenError):
        raise _customer_authority_required() from None
    except ActionDecisionConflictError:
        raise _decision_conflict() from None


def _not_found() -> PublicAPIError:
    return PublicAPIError(404, "action_request_not_found", "action request not found")


def _customer_authority_required() -> PublicAPIError:
    return PublicAPIError(403, "customer_authority_required", "customer authority is required")


def _decision_conflict() -> PublicAPIError:
    return PublicAPIError(
        409, "action_decision_conflict", "action decision conflicts with current state"
    )
