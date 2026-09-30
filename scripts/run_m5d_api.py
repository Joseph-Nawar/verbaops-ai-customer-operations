"""Start the public VerbaOps API with an explicitly chosen M5D DEV profile."""

from __future__ import annotations

import argparse

import uvicorn

from verbaops.agent.evaluation import GroundingCandidate
from verbaops.api.app import create_app
from verbaops.auth.context import Role, TrustedContext
from verbaops.auth.development import DevelopmentAuthProvider
from verbaops.auth.provider import OpaqueCredential
from verbaops.config.settings import Environment, Settings
from verbaops.evaluation.m5d_run_identity import build_agent_evaluation_profile
from verbaops.retrieval.evidence_gate import EvidenceGate


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
    app = create_app(settings=settings, auth_provider=provider, evaluation_profile=profile)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
