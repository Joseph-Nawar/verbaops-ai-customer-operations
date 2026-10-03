"""Stage 6 support-ticket category contract tests."""

from typing import Any, cast

import pytest
from pydantic import SecretStr, ValidationError

from novacommerce.api.app import create_app
from novacommerce.config.settings import Settings
from novacommerce.db.models.support_ticket import SupportTicketCategory
from novacommerce.schemas.writes import SupportTicketCreateRequest

TOKEN = "stage6-category-contract-token-" + "x" * 32
EXPECTED_CATEGORIES = (
    "order",
    "delivery",
    "returns_refunds",
    "product",
    "warranty",
    "payment",
    "account",
    "other",
)


def test_support_ticket_category_is_closed_to_the_frozen_wire_values() -> None:
    assert tuple(category.value for category in SupportTicketCategory) == EXPECTED_CATEGORIES
    for category in EXPECTED_CATEGORIES:
        assert SupportTicketCategory(category).value == category
    with pytest.raises(ValueError):
        SupportTicketCategory("billing")


def test_legacy_ticket_request_omission_defaults_to_other() -> None:
    request = SupportTicketCreateRequest(subject="Delivery", description="Where is my order?")
    assert request.category is SupportTicketCategory.OTHER


def test_ticket_category_is_in_runtime_openapi_request_and_response_contracts() -> None:
    settings = cast(Any, Settings)(_env_file=None, service_token=SecretStr(TOKEN))
    schema = create_app(settings=settings).openapi()

    category = schema["components"]["schemas"]["SupportTicketCategory"]
    assert category["enum"] == list(EXPECTED_CATEGORIES)
    request = schema["components"]["schemas"]["SupportTicketCreateRequest"]
    assert request["properties"]["category"]["default"] == "other"
    assert "category" not in request.get("required", [])
    response = schema["components"]["schemas"]["SupportTicketResponse"]
    assert response["properties"]["category"] == {
        "$ref": "#/components/schemas/SupportTicketCategory"
    }
    assert "category" in response["required"]


def test_unknown_ticket_category_is_rejected_by_request_schema() -> None:
    with pytest.raises(ValidationError):
        SupportTicketCreateRequest.model_validate(
            cast(
                Any,
                {
                    "subject": "Delivery",
                    "description": "Where is my order?",
                    "category": "billing",
                },
            )
        )
