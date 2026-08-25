"""Deterministic, section-aware whitespace-token chunking."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from verbaops.knowledge.parsing import Section

MAX_CHUNK_TOKENS = 180
OVERLAP_TOKENS = 30


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A chunk before document/version metadata is attached."""

    section: str
    chunk_index: int
    content: str


def source_hash(canonical_source: str) -> str:
    """Return the SHA-256 digest of canonical normalized source text."""

    return hashlib.sha256(canonical_source.encode("utf-8")).hexdigest()


def content_hash(canonical_content: str) -> str:
    """Return the SHA-256 digest of canonical normalized chunk text."""

    return hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()


def chunk_sections(sections: list[Section]) -> list[ChunkDraft]:
    """Chunk each section independently and assign one deterministic global index."""

    chunks: list[ChunkDraft] = []
    for section in sections:
        words = section.content.split()
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(start + MAX_CHUNK_TOKENS, len(words))
            chunks.append(
                ChunkDraft(
                    section=section.title,
                    chunk_index=len(chunks),
                    content=" ".join(words[start:end]),
                )
            )
            if end == len(words):
                break
            start = end - OVERLAP_TOKENS
    return chunks
