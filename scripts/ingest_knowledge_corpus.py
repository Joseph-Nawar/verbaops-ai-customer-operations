"""Validate the committed NovaCommerce knowledge manifest and source files."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, cast

from verbaops.knowledge.validation import UploadMetadata, validate_upload


def validate_corpus(root: Path) -> list[dict[str, Any]]:
    manifest_path = root / "knowledge" / "novacommerce" / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = data["documents"]
    logical_versions: set[tuple[str, str, str]] = set()
    for entry in documents:
        key = (entry["slug"], entry["language"], entry["version"])
        if key in logical_versions:
            raise ValueError(f"duplicate logical version: {key}")
        logical_versions.add(key)
        source_path = root / "knowledge" / "novacommerce" / entry["path"]
        if not source_path.is_file():
            raise ValueError(f"missing corpus path: {entry['path']}")
        upload = validate_upload(
            source_path.read_bytes(),
            UploadMetadata(
                slug=entry["slug"],
                title=entry["title"],
                document_type=entry["document_type"],
                language=entry["language"],
                version=entry["version"],
                effective_date=date.fromisoformat(entry["effective_date"]),
                filename=source_path.name,
            ),
        )
        if upload.quarantine:
            raise ValueError(f"quarantined corpus path: {entry['path']}")
    return cast(list[dict[str, Any]], documents)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    documents = validate_corpus(Path(__file__).resolve().parents[1])
    print(f"validated {len(documents)} NovaCommerce knowledge documents")
    if not args.check:
        parser.error("only --check is supported in M5A")


if __name__ == "__main__":
    main()
