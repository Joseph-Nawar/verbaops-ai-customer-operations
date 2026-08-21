"""Contract-first tests for the authenticated, read-only M2C boundary."""

from collections.abc import Callable
from datetime import date, time
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from novacommerce.api.app import create_app
from novacommerce.auth.context import TrustedCustomerContext, parse_customer_context
from novacommerce.auth.service import compare_service_token, escape_like_literal
from novacommerce.clock import FixedUTCClock, delivery_date_range
from novacommerce.config.settings import DatabaseSettings, Environment, Settings
from novacommerce.schemas.delivery_slots import DeliverySlotResponse
from novacommerce.schemas.orders import OrderItemResponse

TOKEN = "m2c-test-token-" + "x" * 32
CUSTOMER_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_settings(**overrides: object) -> Settings:
    construct = cast(Callable[..., Settings], Settings)
    return construct(_env_file=None, service_token=SecretStr(TOKEN), **overrides)


def make_app() -> FastAPI:
    return create_app(settings=make_settings())


async def request(
    app: FastAPI,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


def auth_headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "Basic not-a-bearer", "Bearer wrong"])
async def test_missing_malformed_and_incorrect_bearer_share_generic_401(
    authorization: str | None,
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}
    response = await request(make_app(), "/v1/products/search?q=phone", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "error": {"code": "authentication_required", "message": "Authentication required."}
    }
    assert TOKEN not in response.text


@pytest.mark.asyncio
async def test_customer_header_alone_never_grants_access() -> None:
    response = await request(
        make_app(),
        f"/v1/customers/{CUSTOMER_ID}",
        headers={"X-VerbaOps-Customer-ID": str(CUSTOMER_ID)},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header", "code"),
    [(None, "customer_context_required"), ("not-a-uuid", "invalid_customer_context")],
)
async def test_customer_context_is_required_and_validated_after_auth(
    header: str | None, code: str
) -> None:
    headers = auth_headers()
    if header is not None:
        headers["X-VerbaOps-Customer-ID"] = header
    response = await request(make_app(), f"/v1/customers/{CUSTOMER_ID}", headers=headers)
    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": code, "message": response.json()["error"]["message"]}
    }


def test_runtime_app_requires_a_service_token_but_pure_settings_can_be_built() -> None:
    construct = cast(Callable[..., Settings], Settings)
    settings = construct(_env_file=None)
    assert settings.service_token is None
    with pytest.raises(RuntimeError, match="service token"):
        create_app(settings=settings)


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_deployed_settings_require_a_valid_service_token(environment: Environment) -> None:
    with pytest.raises(ValueError, match="service token"):
        construct = cast(Callable[..., Settings], Settings)
        construct(
            _env_file=None,
            environment=environment,
            database=DatabaseSettings(url=SecretStr("postgresql+asyncpg://u:p@host/db")),
        )


def test_service_token_uses_constant_time_comparison_and_literal_like_escaping() -> None:
    assert compare_service_token(TOKEN, TOKEN)
    assert not compare_service_token(TOKEN, "wrong")
    assert escape_like_literal(r"100%_\\") == "100\\%\\_\\\\\\\\"


def test_customer_context_is_immutable() -> None:
    context = parse_customer_context(str(CUSTOMER_ID))
    assert context == TrustedCustomerContext(customer_id=CUSTOMER_ID)
    with pytest.raises((AttributeError, TypeError)):
        context.customer_id = uuid4()  # type: ignore[misc]


def test_decimal_responses_are_exact_strings_and_derived_values_are_decimal() -> None:
    item = OrderItemResponse(
        order_item_id=CUSTOMER_ID,
        product_id=CUSTOMER_ID,
        sku="SKU",
        product_name="Product",
        quantity=3,
        unit_price=Decimal("499.99"),
        line_total=Decimal("1499.97"),
    )
    assert item.model_dump_json().count('"499.99"') == 1
    assert '"1499.97"' in item.model_dump_json()

    slot = DeliverySlotResponse(
        id=CUSTOMER_ID,
        service_date=date(2026, 8, 21),
        window_start=time(9),
        window_end=time(11),
        capacity=20,
        reserved_count=5,
    )
    assert slot.remaining_capacity == 15
    assert slot.available is True


def test_delivery_dates_use_injected_utc_clock_and_validate_ranges() -> None:
    clock = FixedUTCClock(date(2026, 8, 21))
    assert delivery_date_range(clock) == (date(2026, 8, 21), date(2026, 9, 4))
    with pytest.raises(ValueError, match="31 days"):
        delivery_date_range(clock, from_date=date(2026, 8, 21), to_date=date(2026, 9, 22))
    with pytest.raises(ValueError, match="before"):
        delivery_date_range(clock, from_date=date(2026, 8, 22), to_date=date(2026, 8, 21))


@pytest.mark.asyncio
async def test_query_validation_is_normalized_and_openapi_is_read_only() -> None:
    app = make_app()

    async def fake_session() -> object:
        yield None

    from novacommerce.api.dependencies import get_database_session

    app.dependency_overrides[get_database_session] = fake_session
    response = await request(app, "/v1/products/search", headers=auth_headers())
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "invalid_query", "message": "Request validation failed."}
    }
    schema = (await request(make_app(), "/openapi.json")).json()
    business_paths = {
        path: methods for path, methods in schema["paths"].items() if path.startswith("/v1")
    }
    assert set(business_paths) == {
        "/v1/customers/{customer_id}",
        "/v1/orders/{order_id}",
        "/v1/orders/{order_id}/shipment",
        "/v1/orders/{order_id}/refunds",
        "/v1/products/search",
        "/v1/delivery-slots",
    }
    assert all(set(methods) <= {"get"} for methods in business_paths.values())
    assert "NovaCommerceServiceBearer" in schema["components"]["securitySchemes"]
