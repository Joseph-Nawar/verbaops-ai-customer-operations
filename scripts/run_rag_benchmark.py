"""Run the evaluation-owned RAG benchmark with a fail-closed holdout guard.

The provider-backed adapter is intentionally injected by the runtime harness. This
CLI owns immutable dataset/provenance checks and report serialization; it never
silently substitutes deterministic vectors for a genuine benchmark run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verbaops.evaluation.rag_corpus import audit_rag_corpus, load_rag_cases
from verbaops.evaluation.rag_runner import validate_holdout_provenance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "release_holdout"), default="dev")
    parser.add_argument("--selection", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    dataset = root / "evals/rag/v0.1/questions.jsonl"
    audit = audit_rag_corpus(load_rag_cases(dataset), root)
    if args.split == "release_holdout":
        if args.selection is None:
            parser.error("release_holdout requires --selection")
        try:
            selection = json.loads(args.selection.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            parser.error(f"selection could not be loaded: {error}")
        validate_holdout_provenance(
            selection,
            dataset_sha256=audit.dataset_sha256,
            knowledge_sha256=audit.knowledge_manifest_sha256,
        )
    selected = [case for case in load_rag_cases(dataset) if case.split == args.split]
    print(
        json.dumps(
            {
                "split": args.split,
                "case_count": len(selected),
                "audit": audit.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.split == "release_holdout":
        print(
            "Holdout provenance validated; provider-backed execution must be supplied by the benchmark harness."
        )


if __name__ == "__main__":
    main()
