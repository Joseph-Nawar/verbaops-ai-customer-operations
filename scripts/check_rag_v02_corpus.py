"""Audit rag-v0.2 provenance and enforce its fail-closed split guard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verbaops.evaluation.rag_v02 import RagV02Error, audit_rag_v02, guard_rag_v02_split


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "release_holdout"), default="dev")
    parser.add_argument("--selection", type=Path)
    args = parser.parse_args()
    try:
        guard_rag_v02_split(args.split, selection_path=args.selection)
        audit = audit_rag_v02(Path(__file__).resolve().parents[1])
    except RagV02Error as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(audit.model_dump(mode="json"), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
