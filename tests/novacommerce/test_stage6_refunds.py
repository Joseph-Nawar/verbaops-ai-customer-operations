"""Stage 6 canonical currency and refund approval contracts."""

from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError

from novacommerce.api.app import create_app
from novacommerce.api.dependencies import get_database_session
from novacommerce.config.settings import Settings
from novacommerce.schemas.writes import RefundApprovalReference, RefundCreateRequest

TOKEN = "stage6-refund-contract-token-" + "x" * 32
ACTION_REQUEST_ID = UUID("00000000-0000-0000-0000-0000000000a1")
FINGERPRINT = "a" * 64


def make_app(currency: str | None) -> FastAPI:
    construct = cast(Callable[..., Settings], Settings)
    app = create_app(
        settings=construct(
            _env_file=None,
            service_token=SecretStr(TOKEN),
            tenant_currency=currency,
        )
    )

    async def fake_session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_database_session] = fake_session
    return app


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


async def get(app: FastAPI, path: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def post(
    app: FastAPI,
    path: str,
    *,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body, headers=headers)


def test_refund_approval_reference_requires_uuid_and_lowercase_sha256() -> None:
    reference = RefundApprovalReference(
        action_request_id=ACTION_REQUEST_ID,
        proposal_fingerprint=FINGERPRINT,
    )
    assert reference.action_request_id == ACTION_REQUEST_ID
    assert reference.proposal_fingerprint == FINGERPRINT
    for fingerprint in ("A" * 64, "a" * 63, "g" * 64):
        with pytest.raises(ValidationError):
            RefundApprovalReference(
                action_request_id=ACTION_REQUEST_ID,
                proposal_fingerprint=fingerprint,
            )
    with pytest.raises(ValidationError):
        RefundApprovalReference.model_validate(
            cast(
                Any,
                {
                    "action_request_id": "not-a-uuid",
                    "proposal_fingerprint": FINGERPRINT,
                },
            )
        )


def test_refund_request_omits_absent_approval_from_legacy_fingerprint_body() -> None:
    request = RefundCreateRequest(amount=Decimal("500.01"), reason="approved later")
    assert request.model_dump(mode="json", exclude_none=True) == {
        "amount": "500.01",
        "reason": "approved later",
    }


def test_refund_request_carries_only_the_typed_approval_reference() -> None:
    request = RefundCreateRequest(
        amount=Decimal("500.01"),
        reason="approved later",
        approval_reference=RefundApprovalReference(
            action_request_id=ACTION_REQUEST_ID,
            proposal_fingerprint=FINGERPRINT,
        ),
    )
    assert request.approval_reference == RefundApprovalReference(
        action_request_id=ACTION_REQUEST_ID,
        proposal_fingerprint=FINGERPRINT,
    )
    with pytest.raises(ValidationError):
        RefundCreateRequest.model_validate(
            cast(
                Any,
                {
                    "amount": "500.01",
                    "reason": "approved later",
                    "approval_reference": {
                        "action_request_id": str(ACTION_REQUEST_ID),
                        "proposal_fingerprint": FINGERPRINT,
                        "arbitrary": "not allowed",
                    },
                },
            )
        )


@pytest.mark.asyncio
async def test_tenant_currency_route_is_authenticated_and_returns_only_currency() -> None:
    app = make_app("USD")
    unauthenticated = await get(app, "/v1/tenant-config/currency")
    assert unauthenticated.status_code == 401

    response = await get(app, "/v1/tenant-config/currency", headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == {"currency_code": "USD"}

    paths = app.openapi()["paths"]
    assert set(paths["/v1/tenant-config/currency"]) == {"get"}
    assert (
        paths["/v1/tenant-config/currency"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/TenantCurrencyResponse"
    )
    assert paths["/v1/tenant-config/currency"]["get"]["security"] == [
        {"NovaCommerceServiceBearer": []}
    ]


@pytest.mark.asyncio
async def test_missing_tenant_currency_has_a_stable_sanitized_failure() -> None:
    app = make_app(None)
    response = await get(app, "/v1/tenant-config/currency", headers=auth_headers())
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "tenant_currency_unavailable",
            "message": "Tenant currency is unavailable.",
        }
    }
    assert "NOVACOMMERCE" not in response.text


@pytest.mark.asyncio
async def test_refund_write_requires_internal_service_authentication() -> None:
    app = make_app("USD")
    response = await post(
        app,
        "/v1/orders/00000000-0000-0000-0000-000000000001/refunds",
        body={
            "amount": "500.01",
            "reason": "trusted service only",
            "approval_reference": {
                "action_request_id": str(ACTION_REQUEST_ID),
                "proposal_fingerprint": FINGERPRINT,
            },
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_refund_workflow_fails_closed_before_database_when_currency_is_missing() -> None:
    app = make_app(None)
    headers = {
        **auth_headers(),
        "X-VerbaOps-Customer-ID": "00000000-0000-0000-0000-000000000002",
        "Idempotency-Key": "m6b-missing-currency",
    }
    response = await post(
        app,
        "/v1/orders/00000000-0000-0000-0000-000000000001/refunds",
        headers=headers,
        body={"amount": "1.00", "reason": "must fail closed"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tenant_currency_unavailable"


@pytest.mark.asyncio
async def test_malformed_approval_reference_is_rejected_without_echoing_value() -> None:
    app = make_app("USD")
    invalid_fingerprint = "A" * 64
    headers = {
        **auth_headers(),
        "X-VerbaOps-Customer-ID": "00000000-0000-0000-0000-000000000002",
        "Idempotency-Key": "m6b-malformed-reference",
    }
    response = await post(
        app,
        "/v1/orders/00000000-0000-0000-0000-000000000001/refunds",
        headers=headers,
        body={
            "amount": "500.01",
            "reason": "malformed reference",
            "approval_reference": {
                "action_request_id": str(ACTION_REQUEST_ID),
                "proposal_fingerprint": invalid_fingerprint,
            },
        },
    )
    assert response.status_code == 422
    assert invalid_fingerprint not in response.text
