"""Regenerate provider-free M5D-B case taxonomy and aggregate audits."""

from __future__ import annotations

from pathlib import Path

from verbaops.evaluation.m5d_b2_forensics import write_analysis


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = write_analysis(root, root / "evals/rag/v0.2/analysis")
    for path in paths:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
