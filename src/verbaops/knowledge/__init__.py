"""Versioned knowledge ingestion domain."""

from verbaops.knowledge.chunking import ChunkDraft, chunk_sections, content_hash, source_hash
from verbaops.knowledge.parsing import Section, detect_sections, normalize_markdown
from verbaops.knowledge.validation import (
    UploadMetadata,
    UploadValidationError,
    ValidatedUpload,
    validate_upload,
)

__all__ = [
    "ChunkDraft",
    "Section",
    "UploadMetadata",
    "UploadValidationError",
    "ValidatedUpload",
    "chunk_sections",
    "content_hash",
    "detect_sections",
    "normalize_markdown",
    "source_hash",
    "validate_upload",
]
