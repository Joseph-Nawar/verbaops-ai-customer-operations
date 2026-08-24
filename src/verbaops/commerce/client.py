"""Authenticated HTTP-only NovaCommerce read client."""

from collections.abc import Mapping
from datetime import date
from typing import Any, TypeVar, cast
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from verbaops.commerce.errors import (
    CommerceAuthenticationError,
    CommerceNotFoundError,
    CommerceProtocolError,
    CommerceTimeoutError,
    CommerceUnavailableError,
)
from verbaops.commerce.models import (
    DeliverySlotResponse,
    OrderResponse,
    ProductSearchResponse,
    RefundResponse,
    ShipmentResponse,
)
from verbaops.config import CommerceSettings

ResponseT = TypeVar("ResponseT")


class CommerceClient:
    """Call only the authenticated, read-only NovaCommerce HTTP endpoints."""

    def __init__(self, settings: CommerceSettings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http_client = http_client
        self._base_url = settings.base_url.rstrip("/")

    def __repr__(self) -> str:
        """Avoid rendering settings, URLs, headers, or credentials."""

        return f"{type(self).__name__}(...)"

    async def get_order(self, order_id: UUID, customer_id: UUID) -> OrderResponse:
        """Fetch one customer-scoped order."""

        return await self._get(
            f"/v1/orders/{order_id}",
            OrderResponse,
            customer_id=customer_id,
        )

    async def get_shipment(self, order_id: UUID, customer_id: UUID) -> ShipmentResponse:
        """Fetch one customer-scoped shipment."""

        return await self._get(
            f"/v1/orders/{order_id}/shipment",
            ShipmentResponse,
            customer_id=customer_id,
        )

    async def get_refunds(self, order_id: UUID, customer_id: UUID) -> list[RefundResponse]:
        """Fetch customer-scoped refunds for one order."""

        return await self._get(
            f"/v1/orders/{order_id}/refunds",
            list[RefundResponse],
            customer_id=customer_id,
        )

    async def search_products(self, query: str, limit: int) -> ProductSearchResponse:
        """Search products using the bounded read-client query shape."""

        return await self._get(
            "/v1/products/search",
            ProductSearchResponse,
            params={"q": query, "limit": limit, "offset": 0},
        )

    async def list_delivery_slots(
        self,
        date_from: date,
        date_to: date,
        available_only: bool,
    ) -> list[DeliverySlotResponse]:
        """Fetch delivery slots for a bounded date range."""

        return await self._get(
            "/v1/delivery-slots",
            list[DeliverySlotResponse],
            params={
                "from_date": date_from.isoformat(),
                "to_date": date_to.isoformat(),
                "available_only": available_only,
            },
        )

    async def _get(
        self,
        path: str,
        response_type: Any,
        *,
        params: Mapping[str, str | int | bool] | None = None,
        customer_id: UUID | None = None,
    ) -> ResponseT:
        headers = {"Authorization": f"Bearer {self._settings.service_token.get_secret_value()}"}
        if customer_id is not None:
            headers["X-VerbaOps-Customer-ID"] = str(customer_id)

        for attempt in range(2):
            try:
                response = await self._http_client.get(
                    f"{self._base_url}{path}",
                    headers=headers,
                    params=params,
                    timeout=self._settings.timeout_seconds,
                )
            except httpx.TimeoutException:
                if attempt == 0:
                    continue
                raise CommerceTimeoutError() from None
            except httpx.TransportError:
                if attempt == 0:
                    continue
                raise CommerceUnavailableError() from None

            if response.status_code in (502, 503, 504) and attempt == 0:
                continue
            self._raise_for_status(response)
            return cast(ResponseT, self._parse(response, response_type))

        raise CommerceUnavailableError()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status_code = response.status_code
        if status_code in (401, 403):
            raise CommerceAuthenticationError()
        if status_code == 404:
            raise CommerceNotFoundError()
        if status_code == 429:
            raise CommerceUnavailableError()
        if status_code >= 500:
            raise CommerceUnavailableError()
        if status_code >= 400 or status_code < 200:
            raise CommerceProtocolError()

    @staticmethod
    def _parse(response: httpx.Response, response_type: Any) -> Any:
        try:
            payload = response.json()
            return TypeAdapter(response_type).validate_python(payload)
        except (UnicodeDecodeError, ValueError, TypeError, ValidationError):
            raise CommerceProtocolError() from None
