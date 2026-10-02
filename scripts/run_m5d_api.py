"""Start the public VerbaOps API with an explicitly chosen M5D DEV profile."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from verbaops.agent.evaluation import GroundingCandidate
from verbaops.api.app import create_app
from verbaops.auth.context import Role, TrustedContext
from verbaops.auth.development import DevelopmentAuthProvider
from verbaops.auth.provider import OpaqueCredential
from verbaops.config.settings import Environment, Settings
from verbaops.evaluation.m5d_run_identity import (
    build_agent_evaluation_profile,
    require_canonical_run_directory,
)
from verbaops.retrieval.evidence_gate import EvidenceGate

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", choices=tuple(gate.value for gate in EvidenceGate), required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument(
        "--grounding",
        choices=tuple(candidate.value for candidate in GroundingCandidate),
        required=True,
    )
    parser.add_argument("--model-candidate", choices=("M0", "M1"), default="M0")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--p4-run-dir", type=Path)
    parser.add_argument("--p4-run-id")
    parser.add_argument("--p5-run-dir", type=Path)
    parser.add_argument("--p5-run-id")
    args = parser.parse_args()
    settings = Settings()
    if settings.environment not in (Environment.DEVELOPMENT, Environment.TEST):
        raise RuntimeError("M5D API runner requires development or test environment")
    trusted_context = TrustedContext(
        principal_id=settings.auth.development_principal_id,
        tenant_id=settings.auth.development_tenant_id,
        customer_id=settings.auth.development_customer_id,
        roles=frozenset({Role.CUSTOMER}),
    )
    provider = DevelopmentAuthProvider(
        {OpaqueCredential(settings.auth.development_token.get_secret_value()): trusted_context},
        environment=settings.environment,
    )
    profile = build_agent_evaluation_profile(
        args.grounding,
        evidence_gate=args.gate,
        evidence_gate_threshold=args.threshold,
        model_candidate=args.model_candidate,
    )
    is_p4 = profile.grounding_candidate is GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS
    is_p5 = profile.grounding_candidate is GroundingCandidate.P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS
    if is_p4:
        if args.p4_run_dir is None or args.p4_run_id is None:
            raise ValueError("P4 API requires --p4-run-dir and --p4-run-id")
        require_canonical_run_directory(ROOT, args.p4_run_dir, run_id=args.p4_run_id)
    elif args.p4_run_dir is not None or args.p4_run_id is not None:
        raise ValueError("P4 trace arguments are valid only for P4")
    if is_p5:
        if args.p5_run_dir is None or args.p5_run_id is None:
            raise ValueError("P5 API requires --p5-run-dir and --p5-run-id")
        require_canonical_run_directory(ROOT, args.p5_run_dir, run_id=args.p5_run_id)
    elif args.p5_run_dir is not None or args.p5_run_id is not None:
        raise ValueError("P5 trace arguments are valid only for P5")
    app = create_app(
        settings=settings,
        auth_provider=provider,
        evaluation_profile=profile,
        p4_trace_run_directory=args.p4_run_dir,
        p4_trace_run_id=args.p4_run_id,
        p5_trace_run_directory=args.p5_run_dir,
        p5_trace_run_id=args.p5_run_id,
    )
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
