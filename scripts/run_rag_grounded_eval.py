"""Checkpoint-safe entry point for the real Stage 5 grounded-answer evaluator."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from verbaops.evaluation.rag_corpus import audit_rag_corpus, load_rag_cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    audit = audit_rag_corpus(load_rag_cases(root / "evals/rag/v0.1/questions.jsonl"), root)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.run_dir / "grounded_cases.jsonl"
    if not checkpoint.exists():
        checkpoint.write_text("", encoding="utf-8")
    metadata = {
        "dataset_version": audit.dataset_version,
        "dataset_sha256": audit.dataset_sha256,
        "knowledge_manifest_sha256": audit.knowledge_manifest_sha256,
        "started_at": datetime.now(UTC).isoformat(),
        "credentials_persisted": False,
    }
    (args.run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, sort_keys=True))


if __name__ == "__main__":
    main()
