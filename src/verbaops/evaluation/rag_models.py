"""Immutable models for the frozen Stage 5 RAG evaluation corpus."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RagModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RagLocator(RagModel):
    document_slug: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    section: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)

    def key(self) -> tuple[str, str, str, int]:
        return (self.document_slug, self.document_version, self.section, self.chunk_index)


class RelevanceJudgment(RagLocator):
    relevance_grade: Literal[0, 1, 2]


class ExpectedFact(RagModel):
    fact_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    supporting_locators: tuple[RagLocator, ...] = Field(min_length=1)


class RagCase(RagModel):
    case_id: str = Field(min_length=1)
    dataset_version: Literal["rag-v0.1"]
    split: Literal["dev", "release_holdout"]
    language: Literal["en"]
    category: Literal[
        "shipping",
        "returns",
        "refunds",
        "warranty",
        "payments",
        "privacy",
        "product-guides",
        "faq",
        "no-answer",
    ]
    query: str = Field(min_length=1)
    answerable: bool
    expected_answer: str = Field(min_length=1)
    relevance_judgments: tuple[RelevanceJudgment, ...]
    expected_facts: tuple[ExpectedFact, ...]

    @model_validator(mode="after")
    def validate_answerability(self) -> RagCase:
        positive = [j for j in self.relevance_judgments if j.relevance_grade > 0]
        if self.answerable and not positive:
            raise ValueError("answerable cases require positive relevance")
        if not self.answerable and (positive or self.expected_facts):
            raise ValueError("no-answer cases cannot contain positive evidence or facts")
        return self


class RagCorpusAudit(RagModel):
    dataset_version: str
    language: str
    case_count: int = Field(ge=0)
    split_counts: dict[str, int]
    category_counts: dict[str, int]
    dataset_sha256: str = Field(min_length=64, max_length=64)
    knowledge_manifest_sha256: str = Field(min_length=64, max_length=64)
    chunk_count: int = Field(ge=0)
    chunking: dict[str, int]


class MetricResult(RagModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_denominator(self) -> MetricResult:
        if self.denominator == 0:
            if self.numerator != 0 or self.value is not None:
                raise ValueError("zero-denominator metric must have no value")
        elif self.value is not None and abs(self.value - self.numerator / self.denominator) > 1e-12:
            raise ValueError("metric value does not match numerator and denominator")
        return self

    def as_dict(self) -> dict[str, Any]:
        return {"numerator": self.numerator, "denominator": self.denominator, "value": self.value}


class GroundednessResult(RagModel):
    recognized: int = Field(ge=0)
    supported: int = Field(ge=0)
    unsupported: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> GroundednessResult:
        if self.supported + self.unsupported != self.recognized:
            raise ValueError("groundedness counts must add up")
        return self
