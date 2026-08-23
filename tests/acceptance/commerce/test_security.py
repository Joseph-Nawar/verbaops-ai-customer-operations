"""Authentication and trusted-customer behavior over HTTP."""

from uuid import uuid4

import httpx

from .conftest import scenario_id


def test_missing_and_wrong_auth_are_same_generic_401(
    client: httpx.Client, manifest: dict[str, object]
) -> None:
    customer = scenario_id(manifest, "customer_primary")
    path = f"/v1/customers/{customer}"
    missing = client.get(path)
    wrong = client.get(path, headers={"Authorization": "Bearer wrong"})
    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["www-authenticate"] == wrong.headers["www-authenticate"] == "Bearer"
    assert (
        missing.json()
        == wrong.json()
        == {"error": {"code": "authentication_required", "message": "Authentication required."}}
    )


def test_customer_header_alone_never_grants_access(
    client: httpx.Client, manifest: dict[str, object]
) -> None:
    customer = scenario_id(manifest, "customer_primary")
    response = client.get(f"/v1/customers/{customer}", headers={"X-VerbaOps-Customer-ID": customer})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_authenticated_customer_context_errors_are_stable(
    client: httpx.Client,
    authenticated_headers: dict[str, str],
    manifest: dict[str, object],
) -> None:
    customer = scenario_id(manifest, "customer_primary")
    missing = client.get(f"/v1/customers/{customer}", headers=authenticated_headers)
    malformed = client.get(
        f"/v1/customers/{customer}",
        headers={**authenticated_headers, "X-VerbaOps-Customer-ID": "not-a-uuid"},
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "customer_context_required"
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "invalid_customer_context"


def test_query_validation_is_safe_and_normalized(
    client: httpx.Client, authenticated_headers: dict[str, str]
) -> None:
    response = client.get("/v1/products/search", headers=authenticated_headers, params={"q": "   "})
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "invalid_query", "message": "Request validation failed."}
    }


def test_random_resource_and_other_customer_have_identical_404(
    client: httpx.Client, primary_headers: dict[str, str], manifest: dict[str, object]
) -> None:
    other = scenario_id(manifest, "order_other_customer")
    nonexistent = str(uuid4())
    other_response = client.get(f"/v1/orders/{other}", headers=primary_headers)
    missing_response = client.get(f"/v1/orders/{nonexistent}", headers=primary_headers)
    assert other_response.status_code == missing_response.status_code == 404
    assert (
        other_response.json()
        == missing_response.json()
        == {"error": {"code": "resource_not_found", "message": "Resource not found."}}
    )
