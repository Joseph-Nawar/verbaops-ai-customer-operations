"""Audit the committed Stage 4 golden corpus without a model or database."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.corpus import CorpusAuditError, audit_corpus, load_manifest

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "evals/agent/v0.1"


def main() -> int:
    """Load, audit, and print the exact corpus contract."""

    try:
        manifest = load_manifest(CORPUS_DIR / "manifest.json")
        cases_path = CORPUS_DIR / "cases.jsonl"
        cases = load_cases(cases_path)
        scenario_manifest = json.loads(
            (ROOT / "tests/acceptance/fixtures/novacommerce-scenarios.json").read_text(encoding="utf-8")
        )
        audit = audit_corpus(manifest, cases, scenario_manifest)
    except (OSError, json.JSONDecodeError, CorpusAuditError) as error:
        print(f"Corpus audit failed: {error}")
        return 1
    dataset_sha256 = hashlib.sha256((CORPUS_DIR / "cases.jsonl").read_bytes()).hexdigest()
    print("VerbaOps Text Agent Evaluation Corpus v0.1")
    print(f"Dataset: {manifest.dataset_version}")
    print(f"Cases: {audit.case_count}")
    print(f"Splits: dev: {audit.split_counts['dev']}, release_holdout: {audit.split_counts['release_holdout']}")
    print("Categories:")
    for category, count in audit.category_counts.items():
        print(f"  {category}: {count}")
    print(f"SHA256: {dataset_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
