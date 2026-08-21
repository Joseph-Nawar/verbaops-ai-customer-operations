"""Shared immutable response-model behavior."""

from decimal import Decimal
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, field_serializer


class ResponseModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        from_attributes=True,
        extra="forbid",
        frozen=True,
    )

    @field_serializer("*", when_used="json")
    def serialize_decimal(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return format(value, ".2f")
        return value
