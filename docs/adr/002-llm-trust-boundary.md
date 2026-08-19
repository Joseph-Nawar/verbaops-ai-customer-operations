# ADR-002: The LLM is not a trust or authorization boundary

Status: Accepted
Date: 2026-08-19

## Context

Language models are probabilistic and can follow adversarial, incorrect, or injected instructions. Customer and business actions require deterministic security and policy guarantees.

## Decision

Treat the LLM as an untrusted reasoning/language component. It may interpret language, ask clarifying questions, reason over evidence, select exposed tools, propose typed arguments, summarize, and generate responses. It may not authenticate users, determine trusted tenant context, grant permissions, access business databases directly, approve high-risk actions, bypass confirmation/HITL, execute arbitrary code, modify audit records, or treat retrieved documents as trusted instructions.

## Consequences

The platform needs server-side trusted context, schemas, deterministic policy, explicit confirmation, human approval, authenticated APIs, and result verification. Prompt-based safety remains useful defense-in-depth but cannot substitute for these controls.

## Alternatives considered

- Trust the model with authorization: rejected because probabilistic output is not a security control.
- Allow direct database tools with prompt restrictions: rejected because the database boundary would be bypassed.
