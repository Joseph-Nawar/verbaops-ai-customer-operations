"""Rescore one preserved genuine run without invoking a provider."""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import UUID

from verbaops.evaluation.finalization import (
    finalize_recovery_bundle,
    load_recovery_bundle,
    rescore_safety_results,
    write_recovery_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
RECOVERY_ROOT = ROOT / "artifacts/eval_runs"
BASELINE_JSON = ROOT / "evals/baselines/stage4-agent-v0.1-baseline.json"
BASELINE_MARKDOWN = ROOT / "evals/baselines/stage4-agent-v0.1-baseline.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--evaluator-sha", required=True)
    args = parser.parse_args()
    run_id = UUID(args.run_id)
    source = RECOVERY_ROOT / str(run_id) / "recovery"
    destination = source / "rescored-safety"
    loaded_id, execution_sha, summary, results = load_recovery_bundle(source)
    if loaded_id != run_id:
        raise ValueError("recovery run ID does not match the requested run")
    corrected_summary, corrected_results = rescore_safety_results(summary, results)
    write_recovery_bundle(destination, corrected_summary, corrected_results, execution_sha)
    finalize_recovery_bundle(
        destination,
        BASELINE_JSON,
        BASELINE_MARKDOWN,
        evaluator_git_sha=args.evaluator_sha,
    )
    unauthorized = sum(
        int(result.observed_outcome["safety"]["unauthorized_action"])
        for result in corrected_results
    )
    critical = sum(
        int(result.observed_outcome["safety"]["severity"] == "S4") for result in corrected_results
    )
    print(
        f"RESCORED_RUN={run_id} CASES={len(corrected_results)} "
        f"UNAUTHORIZED={unauthorized} S4={critical} PROVIDER_CALLS=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
