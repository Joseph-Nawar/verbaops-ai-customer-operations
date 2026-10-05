"""Authenticated HTTP-only NovaCommerce read client."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, TypeVar, cast
from uuid import UUID

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from verbaops.commerce.errors import (
    CommerceAuthenticationError,
    CommerceNotFoundError,
    CommerceProtocolError,
    CommerceTimeoutError,
    CommerceUnavailableError,
    CommerceWriteAmbiguousError,
    CommerceWritePreDispatchError,
    CommerceWriteRejected,
)
from verbaops.commerce.models import (
    CancelOrderResponse,
    DeliverySlotResponse,
    OrderResponse,
    ProductSearchResponse,
    RefundApprovalReference,
    RefundCreateRequest,
    RefundResponse,
    RescheduleDeliveryRequest,
    ReturnCreateRequest,
    ReturnResponse,
    ShipmentResponse,
    SupportTicketCreateRequest,
    SupportTicketResponse,
    TenantCurrencyResponse,
    WriteRefundResponse,
)
from verbaops.config import CommerceSettings

ResponseT = TypeVar("ResponseT")


@dataclass(frozen=True, slots=True)
class CommerceWriteResult[WriteResponseT]:
    """Typed successful response and bounded idempotency metadata."""

    response: WriteResponseT
    status_code: int
    replayed: bool


class CommerceClient:
    """Call the fixed authenticated NovaCommerce read and internal write endpoints."""

    def __init__(self, settings: CommerceSettings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http_client = http_client
        self._base_url = settings.base_url.rstrip("/")

    def __repr__(self) -> str:
        """Avoid rendering settings, URLs, headers, or credentials."""

        return f"{type(self).__name__}(...)"

    @property
    def tenant_id(self) -> UUID:
        """Return the one tenant this Commerce connection is configured to serve."""

        return self._settings.tenant_id

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

    async def get_return(self, return_id: UUID, customer_id: UUID) -> ReturnResponse:
        """Fetch one exact customer-scoped return resource."""

        return await self._get(
            f"/v1/returns/{return_id}",
            ReturnResponse,
            customer_id=customer_id,
        )

    async def get_support_ticket(self, ticket_id: UUID, customer_id: UUID) -> SupportTicketResponse:
        """Fetch one exact customer-scoped support-ticket resource."""

        return await self._get(
            f"/v1/support-tickets/{ticket_id}",
            SupportTicketResponse,
            customer_id=customer_id,
        )

    async def cancel_order(
        self, order_id: UUID, customer_id: UUID, idempotency_key: UUID
    ) -> CommerceWriteResult[CancelOrderResponse]:
        """Cancel one order through the fixed NovaCommerce route."""

        return await self._post_write(
            f"/v1/orders/{order_id}/cancel",
            {},
            CancelOrderResponse,
            customer_id=customer_id,
            idempotency_key=idempotency_key,
        )

    async def reschedule_delivery(
        self,
        order_id: UUID,
        customer_id: UUID,
        delivery_slot_id: UUID,
        idempotency_key: UUID,
    ) -> CommerceWriteResult[ShipmentResponse]:
        """Reschedule one order to the fixed delivery slot."""

        request = RescheduleDeliveryRequest(delivery_slot_id=delivery_slot_id)
        return await self._post_write(
            f"/v1/orders/{order_id}/reschedule",
            request,
            ShipmentResponse,
            customer_id=customer_id,
            idempotency_key=idempotency_key,
        )

    async def create_return(
        self,
        customer_id: UUID,
        request: ReturnCreateRequest,
        idempotency_key: UUID,
    ) -> CommerceWriteResult[ReturnResponse]:
        """Create a return request through the one fixed collection route."""

        return await self._post_write(
            "/v1/returns",
            request,
            ReturnResponse,
            customer_id=customer_id,
            idempotency_key=idempotency_key,
        )

    async def create_support_ticket(
        self,
        customer_id: UUID,
        request: SupportTicketCreateRequest,
        idempotency_key: UUID,
    ) -> CommerceWriteResult[SupportTicketResponse]:
        """Create a support ticket through the one fixed collection route."""

        return await self._post_write(
            "/v1/support-tickets",
            request,
            SupportTicketResponse,
            customer_id=customer_id,
            idempotency_key=idempotency_key,
        )

    async def request_refund(
        self,
        order_id: UUID,
        customer_id: UUID,
        request: RefundCreateRequest,
        approval_reference: RefundApprovalReference | None,
        idempotency_key: UUID,
    ) -> CommerceWriteResult[WriteRefundResponse]:
        """Request a refund with only the executor-supplied durable evidence."""

        body = request.model_copy(update={"approval_reference": approval_reference}).model_dump(
            mode="json"
        )
        return await self._post_write(
            f"/v1/orders/{order_id}/refunds",
            body,
            WriteRefundResponse,
            customer_id=customer_id,
            idempotency_key=idempotency_key,
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

    async def get_tenant_currency(self) -> TenantCurrencyResponse | None:
        """Fetch canonical tenant currency, returning None only when unconfigured."""

        return await self._get(
            "/v1/tenant-config/currency",
            TenantCurrencyResponse,
            missing_error_code="tenant_currency_unavailable",
        )

    async def _get(
        self,
        path: str,
        response_type: Any,
        *,
        params: Mapping[str, str | int | bool] | None = None,
        customer_id: UUID | None = None,
        missing_error_code: str | None = None,
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

            if (
                missing_error_code is not None
                and response.status_code == 503
                and _response_error_code(response) == missing_error_code
            ):
                return cast(ResponseT, None)
            if response.status_code in (502, 503, 504) and attempt == 0:
                continue
            self._raise_for_status(response)
            return cast(ResponseT, self._parse(response, response_type))

        raise CommerceUnavailableError()

    async def _post_write(
        self,
        path: str,
        request: BaseModel | dict[str, Any],
        response_type: Any,
        *,
        customer_id: UUID,
        idempotency_key: UUID,
    ) -> CommerceWriteResult[Any]:
        """Perform exactly one dispatch; only the executor may retry a safe failure."""

        headers = {
            "Authorization": f"Bearer {self._settings.service_token.get_secret_value()}",
            "X-VerbaOps-Customer-ID": str(customer_id),
            "Idempotency-Key": str(idempotency_key),
        }
        body = request.model_dump(mode="json") if isinstance(request, BaseModel) else request
        try:
            response = await self._http_client.post(
                f"{self._base_url}{path}",
                headers=headers,
                json=body,
                timeout=self._settings.timeout_seconds,
            )
        except (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError):
            raise CommerceWritePreDispatchError() from None
        except httpx.TransportError:
            raise CommerceWriteAmbiguousError(status_code=None, error_code=None) from None

        status_code = response.status_code
        error_code = _response_error_code(response)
        if status_code == 503 and error_code == "write_outcome_unknown":
            raise CommerceWriteAmbiguousError(
                status_code=status_code,
                error_code=error_code,
            )
        if 400 <= status_code < 500 and status_code not in {408, 429}:
            raise CommerceWriteRejected(
                status_code=status_code,
                error_code=error_code,
            )
        if not 200 <= status_code < 300:
            raise CommerceWriteAmbiguousError(
                status_code=status_code,
                error_code=error_code,
            )
        try:
            payload = response.json()
            typed_response = TypeAdapter(response_type).validate_python(payload)
        except (UnicodeDecodeError, ValueError, TypeError, ValidationError):
            raise CommerceWriteAmbiguousError(
                status_code=status_code,
                error_code=None,
            ) from None
        return CommerceWriteResult(
            response=typed_response,
            status_code=status_code,
            replayed=response.headers.get("X-Idempotent-Replay", "").lower() == "true",
        )

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


def _response_error_code(response: httpx.Response) -> str | None:
    """Read only the bounded API error code needed to distinguish missing config."""

    try:
        payload = response.json()
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) and len(code) <= 128 else None
