"""Immutable retrieval and reranking value objects."""

from dataclasses import dataclass
from datetime import date
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

