from __future__ import annotations

import asyncio
from argparse import Namespace

import pytest
from scripts.run_m5d_stage4_dev_eval import _run


def _args(
    *,
    split: str = "dev",
    grounding: str = "P4_EVIDENCE_LINKED_SINGLE_PASS",
    gate: str = "G2_TOP_EVIDENCE_CROSS_ENCODER",
    threshold: float = 0.2554669,
) -> Namespace:
    return Namespace(
        split=split,
        grounding=grounding,
        model_candidate="M0",
        gate=gate,
        threshold=threshold,
        database_url=None,
        token=None,
    )


def test_stage4_dev_runner_accepts_p4_without_starting_inference() -> None:
    with pytest.raises(ValueError, match="database and public API bearer token"):
        asyncio.run(_run(_args()))


def test_stage4_dev_runner_rejects_p4_release_holdout_before_loading_cases() -> None:
    with pytest.raises(ValueError, match="only --split dev"):
        asyncio.run(_run(_args(split="release_holdout")))


def test_stage4_dev_runner_rejects_unknown_candidate() -> None:
    with pytest.raises(ValueError, match="grounding candidate is not preregistered"):
        asyncio.run(_run(_args(grounding="P9_UNKNOWN")))


@pytest.mark.parametrize(
    ("gate", "threshold"),
    [("G1_DENSE_SIMILARITY", 0.2554669), ("G2_TOP_EVIDENCE_CROSS_ENCODER", 0.4)],
)
def test_stage4_dev_runner_rejects_p4_profile_outside_frozen_g2(
    gate: str, threshold: float
) -> None:
    with pytest.raises(ValueError, match="P4 requires the frozen G2 gate and threshold"):
        asyncio.run(_run(_args(gate=gate, threshold=threshold)))
