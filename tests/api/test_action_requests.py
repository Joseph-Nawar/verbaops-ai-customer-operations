"""Customer action routes accept only fixed, trusted identity-bound decisions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI

from tests.api.conftest import build_context, build_provider, build_settings, request
from verbaops.actions.decisions import (
    ActionDecisionConflictError,
    ActionDecisionForbiddenError,
    ActionFreshnessUnavailableError,
    ActionRequestView,
)
from verbaops.actions.models import ActionState, ActionType, CancelOrderProposal
from verbaops.actions.transitions import ActionRequestNotFoundError
from verbaops.api.dependencies import get_action_decision_service, get_action_reconciler
from verbaops.auth.context import Role, TrustedContext

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
ACTION_ID = UUID("90000000-0000-0000-0000-000000000001")
OWNER = build_context(
    principal_id="90000000-0000-0000-0000-000000000002",
    tenant_id="90000000-0000-0000-0000-000000000003",
    customer_id="90000000-0000-0000-0000-000000000004",
)
OWNER = OWNER.model_copy(update={"roles": frozenset({Role.CUSTOMER})})


def action_view(
    *, state: ActionState = ActionState.AWAITING_CONFIRMATION, fingerprint: str = "a" * 64
) -> ActionRequestView:
    return ActionRequestView(
        action_request_id=ACTION_ID,
        action_type=ActionType.CANCEL_ORDER,
        state=state,
        proposal_fingerprint=fingerprint,
        proposal=CancelOrderProposal(order_id=UUID("90000000-0000-0000-0000-000000000005")),
        safe_summary="Cancel order 90000000-0000-0000-0000-000000000005",
        required_next_actor="customer",
        expires_at=NOW + timedelta(hours=1),
        customer_decision=None,
        result_status=None,
    )


class FakeDecisionService:
    def __init__(self, trusted: TrustedContext) -> None:
        self.owner = trusted
        self.view = action_view()
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def _authorize(self, action_id: UUID, trusted: TrustedContext) -> None:
        if action_id != ACTION_ID or trusted.customer_id != self.owner.customer_id:
            raise ActionRequestNotFoundError("action request not found in customer scope")
        if trusted.roles != frozenset({Role.CUSTOMER}):
            raise ActionDecisionForbiddenError("customer action authority is required")

    async def get_action_request(
        self, action_id: UUID, trusted: TrustedContext
    ) -> ActionRequestView:
        self._authorize(action_id, trusted)
        self.calls.append(("get", (action_id, trusted)))
        return self.view

    async def confirm(
        self, action_id: UUID, trusted: TrustedContext, fingerprint: str
    ) -> ActionRequestView:
        self._authorize(action_id, trusted)
        self.calls.append(("confirm", (action_id, trusted, fingerprint)))
        if fingerprint != self.view.proposal_fingerprint:
            raise ActionDecisionConflictError("action decision conflicts with current state")
        self.view = self.view.model_copy(update={"state": ActionState.SUCCEEDED})
        return self.view

    async def reject(
        self, action_id: UUID, trusted: TrustedContext, fingerprint: str
    ) -> ActionRequestView:
        self._authorize(action_id, trusted)
        self.calls.append(("reject", (action_id, trusted, fingerprint)))
        if fingerprint != self.view.proposal_fingerprint:
            raise ActionDecisionConflictError("action decision conflicts with current state")
        self.view = self.view.model_copy(update={"state": ActionState.REJECTED})
        return self.view


class FakeReconciler:
    def __init__(self, decision_service: FakeDecisionService) -> None:
        self.decision_service = decision_service
        self.calls: list[tuple[UUID, TrustedContext]] = []

    async def reconcile(self, action_id: UUID, trusted: TrustedContext) -> None:
        self.decision_service._authorize(action_id, trusted)
        self.calls.append((action_id, trusted))


def action_app(
    trusted: TrustedContext = OWNER,
    *,
    decision_service_override: FakeDecisionService | None = None,
) -> tuple[FastAPI, FakeDecisionService, FakeReconciler]:
    from verbaops.api.app import create_app

    decision_service = decision_service_override or FakeDecisionService(OWNER)
    reconciler = FakeReconciler(decision_service)
    app = create_app(settings=build_settings(), auth_provider=build_provider(trusted))
    app.dependency_overrides[get_action_decision_service] = lambda: decision_service
    app.dependency_overrides[get_action_reconciler] = lambda: reconciler
    return app, decision_service, reconciler


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer opaque-test-credential"}


@pytest.mark.asyncio
async def test_owner_get_and_decision_routes_use_only_trusted_context() -> None:
    app, service, _ = action_app()

    response = await request(app, "GET", f"/v1/action-requests/{ACTION_ID}", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["action_request_id"] == str(ACTION_ID)

    confirmed = await request(
        app,
        "POST",
        f"/v1/action-requests/{ACTION_ID}/confirmation",
        headers=auth_headers(),
        json={"proposal_fingerprint": "a" * 64},
    )
    assert confirmed.status_code == 200
    call = next(call for call in service.calls if call[0] == "confirm")
    assert call[1][1] == OWNER
    assert call[1][2] == "a" * 64


@pytest.mark.asyncio
async def test_action_routes_require_authenticated_bearer_context() -> None:
    app, service, _ = action_app()

    response = await request(
        app,
        "POST",
        f"/v1/action-requests/{ACTION_ID}/confirmation",
        json={"proposal_fingerprint": "a" * 64},
    )

    assert response.status_code == 401
    assert service.calls == []


class FreshnessUnavailableDecisionService(FakeDecisionService):
    async def get_action_request(
        self, action_id: UUID, trusted: TrustedContext
    ) -> ActionRequestView:
        del action_id, trusted
        raise ActionFreshnessUnavailableError("current action facts are unavailable")

    async def confirm(
        self, action_id: UUID, trusted: TrustedContext, fingerprint: str
    ) -> ActionRequestView:
        del action_id, trusted, fingerprint
        raise ActionFreshnessUnavailableError("current action facts are unavailable")


@pytest.mark.asyncio
async def test_refund_view_and_confirmation_map_freshness_outages_to_503() -> None:
    app, _, _ = action_app(decision_service_override=FreshnessUnavailableDecisionService(OWNER))

    view = await request(app, "GET", f"/v1/action-requests/{ACTION_ID}", headers=auth_headers())
    confirm = await request(
        app,
        "POST",
        f"/v1/action-requests/{ACTION_ID}/confirmation",
        headers=auth_headers(),
        json={"proposal_fingerprint": "a" * 64},
    )

    assert view.status_code == confirm.status_code == 503
    assert view.json()["error"]["code"] == "action_freshness_unavailable"
    assert confirm.json()["error"]["code"] == "action_freshness_unavailable"


@pytest.mark.asyncio
async def test_customer_view_rejects_support_context() -> None:
    support = OWNER.model_copy(update={"roles": frozenset({Role.SUPPORT_AGENT})})
    app, _, _ = action_app(support)

    response = await request(app, "GET", f"/v1/action-requests/{ACTION_ID}", headers=auth_headers())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "customer_authority_required"


@pytest.mark.asyncio
async def test_random_and_cross_customer_ids_have_identical_sanitized_not_found() -> None:
    stranger = build_context(
        principal_id="90000000-0000-0000-0000-000000000006",
        tenant_id=str(OWNER.tenant_id),
        customer_id="90000000-0000-0000-0000-000000000007",
    ).model_copy(update={"roles": frozenset({Role.CUSTOMER})})
    app, _, _ = action_app(stranger)

    cross_owner = await request(
        app, "GET", f"/v1/action-requests/{ACTION_ID}", headers=auth_headers()
    )
    random_id = await request(
        app,
        "GET",
        f"/v1/action-requests/{uuid4()}",
        headers=auth_headers(),
    )

    assert cross_owner.status_code == random_id.status_code == 404
    assert cross_owner.json()["error"]["code"] == "action_request_not_found"
    assert cross_owner.json()["error"]["message"] == random_id.json()["error"]["message"]
    assert cross_owner.json()["error"]["code"] == random_id.json()["error"]["code"]


@pytest.mark.asyncio
async def test_confirmation_and_rejection_accept_exact_fingerprint_only() -> None:
    app, service, _ = action_app()
    path = f"/v1/action-requests/{ACTION_ID}/confirmation"
    extra = await request(
        app,
        "POST",
        path,
        headers=auth_headers(),
        json={"proposal_fingerprint": "a" * 64, "customer_id": str(OWNER.customer_id)},
    )
    wrong = await request(
        app,
        "POST",
        path,
        headers=auth_headers(),
        json={"proposal_fingerprint": "b" * 64},
    )
    rejected = await request(
        app,
        "POST",
        f"/v1/action-requests/{ACTION_ID}/rejection",
        headers=auth_headers(),
        json={"proposal_fingerprint": "a" * 64},
    )

    assert extra.status_code == 422
    assert wrong.status_code == 409
    assert rejected.status_code == 200
    assert [call[0] for call in service.calls] == ["confirm", "reject"]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [Role.SUPPORT_AGENT, Role.SUPPORT_SUPERVISOR])
async def test_support_and_supervisor_contexts_cannot_confirm_as_customer(role: Role) -> None:
    staff = TrustedContext(
        principal_id=uuid4(),
        tenant_id=OWNER.tenant_id,
        customer_id=OWNER.customer_id,
        roles=frozenset({role}),
    )
    app, service, _ = action_app(staff)

    response = await request(
        app,
        "POST",
        f"/v1/action-requests/{ACTION_ID}/confirmation",
        headers=auth_headers(),
        json={"proposal_fingerprint": "a" * 64},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "customer_authority_required"
    assert service.calls == []

    reconciled = await request(
        app,
        "POST",
        f"/v1/action-requests/{ACTION_ID}/reconciliation",
        headers=auth_headers(),
    )
    assert reconciled.status_code == 403


@pytest.mark.asyncio
async def test_reconciliation_accepts_no_body_and_ignores_no_identity_source() -> None:
    app, _, reconciler = action_app()

    response = await request(
        app,
        "POST",
        f"/v1/action-requests/{ACTION_ID}/reconciliation",
        headers=auth_headers(),
    )
    body = await request(
        app,
        "POST",
        f"/v1/action-requests/{ACTION_ID}/reconciliation",
        headers=auth_headers(),
        json={"idempotency_key": str(uuid4()), "state": "succeeded"},
    )

    assert response.status_code == 200
    assert body.status_code == 422
    assert reconciler.calls == [(ACTION_ID, OWNER)]


@pytest.mark.asyncio
async def test_no_execute_or_supervisor_approval_routes_are_registered() -> None:
    app, _, _ = action_app()
    routes = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/v1/action-requests")
        for method in operations
    }
    assert routes == {
        ("GET", "/v1/action-requests/{action_request_id}"),
        ("POST", "/v1/action-requests/{action_request_id}/confirmation"),
        ("POST", "/v1/action-requests/{action_request_id}/rejection"),
        ("POST", "/v1/action-requests/{action_request_id}/reconciliation"),
    }
