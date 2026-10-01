"""Typed models for the frozen evaluation-only P4 response contract."""

from pydantic import BaseModel, ConfigDict, Field


class P4Claim(BaseModel):
    """One proposed extractive claim linked to one supplied evidence item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_text: str = Field(min_length=1)
    evidence_handle: str = Field(min_length=1)
    supporting_excerpt: str = Field(min_length=1)


class P4Response(BaseModel):
    """A P4 knowledge response containing only ordered claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claims: list[P4Claim]


__all__ = ["P4Claim", "P4Response"]
