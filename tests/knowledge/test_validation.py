from datetime import date
from typing import Any

import pytest

from verbaops.knowledge.validation import UploadMetadata, UploadValidationError, validate_upload


def metadata(**overrides: object) -> UploadMetadata:
    values: dict[str, Any] = {
        "slug": "shipping-policy",
        "title": "Shipping Policy",
        "document_type": "policy",
        "language": "en",
        "version": "v1",
        "effective_date": date(2026, 1, 1),
    }
    values.update(overrides)
    return UploadMetadata(**values)


@pytest.mark.parametrize(
    ("source", "error_code"),
    [
        (b"", "empty_normalized_source"),
        (b"plain text", "markdown_required"),
        (b"\xff", "invalid_utf8"),
    ],
)
def test_upload_validation_rejects_invalid_source(source: bytes, error_code: str) -> None:
    with pytest.raises(UploadValidationError, match=error_code):
        validate_upload(source, metadata())


@pytest.mark.parametrize("slug", ["Shipping Policy", "../secret", "UPPER", "a" * 65])
def test_upload_validation_rejects_unsafe_slug(slug: str) -> None:
    with pytest.raises(UploadValidationError, match="invalid_slug"):
        validate_upload(b"# Heading\ntext", metadata(slug=slug))


def test_upload_validation_rejects_oversized_source() -> None:
    with pytest.raises(UploadValidationError, match="source_too_large"):
        validate_upload(b"# Heading\n" + b"a" * (1024 * 1024), metadata())


def test_upload_validation_quarantines_synthetic_secret_and_ignores_identity_fields() -> None:
    upload = validate_upload(
        b"# Support\napi_key=sk-test-123456789012345678901234\ntenant_id=attacker",
        metadata(),
    )

    assert upload.quarantine is True
    assert upload.quarantine_code == "suspicious_content"
    assert not hasattr(upload, "tenant_id")
