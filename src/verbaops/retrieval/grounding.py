"""Server-side citation handle validation and safe grounding finalization."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from verbaops.retrieval.models import RetrievalEvidence

SAFE_GROUNDING_FALLBACK = (
    "I'm unable to verify that information from the available company knowledge."
)
_HANDLE = re.compile(r"\[\[([A-Za-z][A-Za-z0-9_-]*)\]\]")


@dataclass(frozen=True, slots=True)
class GroundedResponse:
    content: str
    citations: tuple[RetrievalEvidence, ...]


class CitationFinalizer:
    """Accept only evidence handles supplied by this retrieval invocation."""

    def finalize(self, content: str, evidence: Sequence[RetrievalEvidence]) -> GroundedResponse:
        by_key = {item.evidence_key: item for item in evidence}
        matches = list(_HANDLE.finditer(content))
        if not matches:
            return GroundedResponse(content=content, citations=())

        ordered_keys: list[str] = []
        for match in matches:
            key = match.group(1)
            if key not in by_key:
                return GroundedResponse(content=SAFE_GROUNDING_FALLBACK, citations=())
            if key not in ordered_keys:
                ordered_keys.append(key)

        numbering = {key: index for index, key in enumerate(ordered_keys, start=1)}
        grounded_content = _HANDLE.sub(lambda match: f"[{numbering[match.group(1)]}]", content)
        return GroundedResponse(
            content=grounded_content,
            citations=tuple(by_key[key] for key in ordered_keys),
        )


__all__ = ["SAFE_GROUNDING_FALLBACK", "CitationFinalizer", "GroundedResponse"]
