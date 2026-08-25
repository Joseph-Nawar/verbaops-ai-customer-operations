"""Upload validation and quarantine rules for untrusted knowledge source."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from verbaops.knowledge.parsing import normalize_markdown

MAX_SOURCE_BYTES = 1024 * 1024
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_SUSPICIOUS = re.compile(
    r"(?:-----BEGIN (?:RSA|OPENSSH|EC|PRIVATE) KEY-----|\bapi[_ -]?key\b|"
    r"\bsecret[_ -]?key\b|\bpassword\s*[:=]|\btoken\s*[:=]|"
    r"\bauthorization\s*:\s*bearer\b|\bsk-[A-Za-z0-9_-]{12,}|"
    r"ignore\s+(?:all\s+)?previous\s+instructions|reveal\s+the\s+system\s+prompt)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class UploadMetadata:
    slug: str
    title: str
    document_type: str
    language: str
    version: str
    effective_date: date
    filename: str = "document.md"


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    metadata: UploadMetadata
    normalized_source: str
    quarantine: bool = False
    quarantine_code: str | None = None


class UploadValidationError(ValueError):
    """A safe validation error identified by a stable code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(f"{code}: {message or code}")


def validate_upload(source: bytes, metadata: UploadMetadata) -> ValidatedUpload:
    """Validate metadata and source; suspicious but parseable source is quarantined."""

    if len(source) > MAX_SOURCE_BYTES:
        raise UploadValidationError("source_too_large")
    if not metadata.filename.lower().endswith(".md"):
        raise UploadValidationError("markdown_required")
    if not _SLUG.fullmatch(metadata.slug) or len(metadata.slug) > 64:
        raise UploadValidationError("invalid_slug")
    if not _VERSION.fullmatch(metadata.version):
        raise UploadValidationError("invalid_version")
    if not 1 <= len(metadata.title) <= 200:
        raise UploadValidationError("invalid_title")
    if not _LANGUAGE.fullmatch(metadata.language):
        raise UploadValidationError("invalid_language")
    if not isinstance(metadata.effective_date, date):
        raise UploadValidationError("invalid_effective_date")
    try:
        normalized = normalize_markdown(source)
    except UnicodeDecodeError as error:
        raise UploadValidationError("invalid_utf8") from error
    if not normalized.strip():
        raise UploadValidationError("empty_normalized_source")
    if "#" not in normalized or not re.search(r"^ {0,3}#{1,6}[ \t]+", normalized, re.MULTILINE):
        raise UploadValidationError("markdown_required")
    if _SUSPICIOUS.search(normalized):
        return ValidatedUpload(
            metadata=metadata,
            normalized_source=normalized,
            quarantine=True,
            quarantine_code="suspicious_content",
        )
    return ValidatedUpload(metadata=metadata, normalized_source=normalized)
