"""Compare a genuine baseline artifact with a candidate evaluation summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verbaops.evaluation.baseline import BaselineArtifact, validate_baseline_artifact
from verbaops.evaluation.compare import compare_artifacts, render_comparison
from verbaops.evaluation.models import EvaluationSummary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path, metavar="BASELINE")
    parser.add_argument("--candidate", required=True, type=Path, metavar="CANDIDATE")
    args = parser.parse_args()
    baseline = validate_baseline_artifact(
        BaselineArtifact.model_validate(json.loads(args.baseline.read_text(encoding="utf-8")))
    )
    candidate = EvaluationSummary.model_validate(
        json.loads(args.candidate.read_text(encoding="utf-8"))
    )
    print(render_comparison(compare_artifacts(baseline, candidate)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
