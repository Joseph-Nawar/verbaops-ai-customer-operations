"""Audit and print provenance for the frozen Stage 5 RAG corpus."""

from __future__ import annotations

import json
from pathlib import Path

from verbaops.evaluation.rag_corpus import audit_rag_corpus, load_rag_cases


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    dataset = root / "evals/rag/v0.1/questions.jsonl"
    audit = audit_rag_corpus(load_rag_cases(dataset), root)
    print(json.dumps(audit.model_dump(mode="json"), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
