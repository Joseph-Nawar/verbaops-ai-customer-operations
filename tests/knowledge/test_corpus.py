import json
from datetime import date
from pathlib import Path

from scripts.ingest_knowledge_corpus import validate_corpus

from verbaops.knowledge.validation import UploadMetadata, validate_upload

ROOT = Path(__file__).parents[2]


def test_required_novacommerce_corpus_manifest_is_complete_and_coherent() -> None:
    documents = validate_corpus(ROOT)
    manifest = json.loads((ROOT / "knowledge/novacommerce/manifest.json").read_text())

    assert len(documents) == 17
    assert {entry["intent"] for entry in documents} == {"current", "historical"}
    assert all(entry["language"] == "en" for entry in documents)
    assert all(entry["path"].endswith(".md") for entry in documents)
    assert all(date.fromisoformat(entry["effective_date"]) for entry in manifest["documents"])


def test_every_manifest_document_is_valid_upload() -> None:
    for entry in json.loads((ROOT / "knowledge/novacommerce/manifest.json").read_text())[
        "documents"
    ]:
        path = ROOT / "knowledge/novacommerce" / entry["path"]
        upload = validate_upload(
            path.read_bytes(),
            UploadMetadata(
                slug=entry["slug"],
                title=entry["title"],
                document_type=entry["document_type"],
                language=entry["language"],
                version=entry["version"],
                effective_date=date.fromisoformat(entry["effective_date"]),
                filename=path.name,
            ),
        )
        assert not upload.quarantine
