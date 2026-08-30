"""Immutable retrieval and reranking value objects."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    chunk_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    document_title: str
    document_slug: str
    document_version: str
    section: str
    effective_date: date
    language: str
    content: str
    chunk_index: int = 0


@dataclass(frozen=True, slots=True)
class DenseHit:
    chunk: KnowledgeHit
    rank: int
    score: float


@dataclass(frozen=True, slots=True)
class LexicalHit:
    chunk: KnowledgeHit
    rank: int
    score: float


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    chunk: KnowledgeHit
    dense_rank: int | None
    dense_score: float | None
    lexical_rank: int | None
    lexical_score: float | None
    rrf_rank: int
    rrf_score: float
    rerank_rank: int | None = None
    rerank_score: float | None = None
    selected: bool = False
    evidence_key: str | None = None


@dataclass(frozen=True, slots=True)
class RerankScore:
    index: int
    score: float


class RetrievalStatus(StrEnum):
    SUCCEEDED = "succeeded"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    evidence_key: str
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    document_title: str
    document_slug: str
    document_version: str
    section: str
    effective_date: date
    content: str
    chunk_index: int = 0


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    invocation_id: UUID
    status: RetrievalStatus
    evidence: tuple[RetrievalEvidence, ...]
    top_score: float | None = None
    error_code: str | None = None
