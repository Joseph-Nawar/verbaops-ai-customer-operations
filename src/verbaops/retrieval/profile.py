"""Versioned retrieval profiles for production and evaluation paths."""

from dataclasses import dataclass
from typing import Literal

from verbaops.knowledge.profiles import EMBEDDING_MODEL, EMBEDDING_PROFILE

RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RetrievalStrategyName = Literal["hybrid_rrf", "hybrid_rrf_rerank"]


@dataclass(frozen=True, slots=True)
class RetrievalProfile:
    """Complete immutable retrieval configuration with provenance."""

    version: str
    strategy: RetrievalStrategyName
    dense_limit: int
    lexical_limit: int
    rrf_k: int
    fused_limit: int
    rerank_limit: int
    final_limit: int
    threshold: float
    embedding_profile: str
    embedding_model: str
    reranker_model: str | None

    @property
    def uses_reranker(self) -> bool:
        return self.strategy == "hybrid_rrf_rerank"


M5B_RETRIEVAL_PROFILE = RetrievalProfile(
    version="knowledge-retrieval-v1",
    strategy="hybrid_rrf_rerank",
    dense_limit=20,
    lexical_limit=20,
    rrf_k=60,
    fused_limit=20,
    rerank_limit=20,
    final_limit=5,
    threshold=0.5,
    embedding_profile=EMBEDDING_PROFILE,
    embedding_model=EMBEDDING_MODEL,
    reranker_model=RERANKER_MODEL,
)

PRODUCTION_RETRIEVAL_PROFILE = RetrievalProfile(
    version="knowledge-retrieval-v1.1",
    strategy="hybrid_rrf",
    dense_limit=20,
    lexical_limit=20,
    rrf_k=60,
    fused_limit=20,
    rerank_limit=20,
    final_limit=5,
    threshold=0.032018442622950824,
    embedding_profile=EMBEDDING_PROFILE,
    embedding_model=EMBEDDING_MODEL,
    reranker_model=None,
)


__all__ = [
    "M5B_RETRIEVAL_PROFILE",
    "PRODUCTION_RETRIEVAL_PROFILE",
    "RERANKER_MODEL",
    "RetrievalProfile",
]
