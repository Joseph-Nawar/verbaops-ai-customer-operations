"""Shared immutable response-model behavior."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        from_attributes=True,
        extra="forbid",
        frozen=True,
    )
