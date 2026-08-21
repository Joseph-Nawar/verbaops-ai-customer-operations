"""Immutable customer context created only after service authentication."""

from dataclasses import dataclass
from uuid import UUID

from novacommerce.api.errors import APIError


@dataclass(frozen=True, slots=True)
class TrustedCustomerContext:
    """Customer identity trusted by customer-owned read services."""

    customer_id: UUID


def parse_customer_context(value: str | None) -> TrustedCustomerContext:
    """Parse the customer header after service authentication has succeeded."""

    if value is None:
        raise APIError(400, "customer_context_required", "Customer context required.")
    try:
        customer_id = UUID(value)
    except ValueError as error:
        raise APIError(400, "invalid_customer_context", "Invalid customer context.") from error
    return TrustedCustomerContext(customer_id=customer_id)
