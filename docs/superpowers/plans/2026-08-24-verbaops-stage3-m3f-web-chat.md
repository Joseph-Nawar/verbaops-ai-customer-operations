# VerbaOps Stage 3 M3F Web Chat Implementation Plan

> **Execution mode:** inline single-agent execution only. Subagents and
> subagent-driven development are prohibited by the user.

**Goal:** Build a minimal Next.js App Router chat over the existing M3E
conversation API, with a server-only bearer-token BFF and a deterministic
browser smoke test, then lock Stage 3.

**Architecture:** `apps/web` contains a strict TypeScript Next.js App Router
application. Browser code calls only same-origin `/api/...` route handlers;
server-only BFF code validates narrow request bodies, injects the configured
VerbaOps bearer token, and forwards only to the three existing M3E endpoints.
The browser smoke test runs the web app against a deterministic local HTTP
backend stub and never boots LiteLLM or NovaCommerce.

**Tech Stack:** Node 24 LTS, pnpm with a committed lockfile, Next.js 16.3.2,
React 19.2.8, TypeScript strict mode, Vitest, React Testing Library, and
Playwright.

**Spec:** `docs/superpowers/specs/2026-08-23-verbaops-stage3-ai-provider-text-agent-design.md`

## Global Constraints

- M3F only; do not add backend business features or alter the M3A-M3E Python
  implementation unless a genuine integration blocker is proven.
- No write tools, RAG, embeddings, Arabic specialization, voice, HITL,
  multi-agent behavior, streaming, or production identity provider.
- The browser never receives `VERBAOPS_API_TOKEN` or any equivalent secret.
- BFF routes are exactly the three corresponding M3E routes; no generic proxy.
- Use exact package versions and Node 24 LTS.
- Keep the existing ten backend CI jobs unchanged; add only `web-quality`.
- No migration, NovaCommerce production, OpenAPI, seed, or LiteLLM changes.
- Every new behavior follows RED, expected failure, minimal GREEN, and a
  focused verification before the next behavior.

## Task 1: Web workspace and BFF contract tests

**Files:**
- Create: `apps/web/package.json`, `apps/web/pnpm-workspace.yaml` if needed,
  `apps/web/tsconfig.json`, `apps/web/next.config.ts`, `apps/web/eslint.config.mjs`,
  `apps/web/vitest.config.ts`, `apps/web/playwright.config.ts`
- Create: `apps/web/src/lib/server/verbaops.ts`
- Create: `apps/web/src/app/api/conversations/route.ts`
- Create: `apps/web/src/app/api/conversations/[conversationId]/messages/route.ts`
- Create: `apps/web/src/app/api/conversations/[conversationId]/route.ts`
- Test: `apps/web/src/lib/server/verbaops.test.ts`
- Test: route handler tests colocated with the BFF modules

**Interfaces:**
- Server helper exports typed `createConversation()`,
  `sendConversationMessage(conversationId, content)`, and
  `getConversation(conversationId, searchParams)`; each uses one fixed
  configured `VERBAOPS_API_BASE_URL` and server-only
  `VERBAOPS_API_TOKEN`.
- Route handlers accept only `{}` for creation, `{content: string}` for
  messages, and an opaque UUID path plus bounded pagination query for GET.
- Safe failures return the backend envelope for HTTP responses and a generic
  `backend_unavailable` envelope for network/time-out failures.

- [ ] Write failing tests for auth-header injection, `cache: "no-store"`,
  successful JSON forwarding, safe backend failure forwarding, network failure
  normalization, token non-disclosure, strict message validation, and rejection
  of identity fields.
- [ ] Run the focused Vitest suite and confirm it fails because the web
  modules do not exist.
- [ ] Implement the smallest server-only helper and three exact route handlers.
- [ ] Run the focused suite and confirm all BFF tests pass.
- [ ] Commit the BFF boundary and tests.

## Task 2: Chat component and UI tests

**Files:**
- Create: `apps/web/src/app/page.tsx`, `apps/web/src/app/layout.tsx`,
  `apps/web/src/app/globals.css`
- Create: `apps/web/src/components/chat.tsx`
- Test: `apps/web/src/components/chat.test.tsx`
- Create: `apps/web/.env.local.example`
- Modify: `.gitignore` only if the existing `.env.*` rule does not cover
  `apps/web/.env.local`

**Interfaces:**
- `Chat` owns `conversationId`, visible messages, draft, pending state, and
  safe user-facing error state.
- First submit calls create once then sends the message; later submits reuse
  the stored ID. Reset clears the ID and visible messages.

- [ ] Write failing RTL tests for first-send creation ordering, clarification
  rendering, second-send reuse, message ordering, duplicate-submit disabling,
  error/retry behavior, reset, and the 8,000-character boundary.
- [ ] Run the focused suite and confirm the expected missing-component failure.
- [ ] Implement the semantic form, labelled textarea, Enter/Shift+Enter
  behavior, loading/error/retry/reset states, and text-only rendering.
- [ ] Run focused tests and confirm GREEN.
- [ ] Add small responsive styling without a UI framework.
- [ ] Commit the chat UI and tests.

## Task 3: Deterministic browser smoke stack

**Files:**
- Create: `apps/web/tests/smoke/backend-stub.ts`
- Create: `apps/web/tests/smoke/web-chat.spec.ts`
- Modify: `apps/web/playwright.config.ts`
- Modify: `apps/web/package.json` scripts

**Interfaces:**
- The stub exposes the three M3E paths, requires the exact generated bearer
  token, records create count and backend calls, and returns clarification then
  grounded deterministic text for the canonical order ID.
- Playwright starts the stub and Next server, sets only server-side env vars,
  and observes browser requests to prove no direct backend-origin request.

- [ ] Write the smoke test and run it against the not-yet-complete app to
  establish the RED failure.
- [ ] Implement the stub and Playwright wiring with no commercial services.
- [ ] Run the smoke test and assert one conversation, clarification, grounded
  response, no token in browser content, and no direct backend request.
- [ ] Commit the smoke stack.

## Task 4: Root tooling, CI, and documentation

**Files:**
- Modify: `.github/workflows/ci.yml` by adding only `web-quality`
- Modify: `Makefile` with thin `web-check` and `web-smoke` wrappers
- Modify: `README.md`
- Modify: Stage 3 spec and master plan only after all M3F verification passes

**Interfaces:**
- `web-quality` installs exact pnpm dependencies with a committed lockfile,
  runs lint, typecheck, unit tests, build, and Playwright smoke using Node 24.
- README documents the read-only Stage 3 path and local web setup without
  claiming unimplemented capabilities.

- [ ] Add CI contract tests first for the job name, pinned actions, Node 24,
  frozen pnpm install, all five web commands, and unchanged backend jobs.
- [ ] Run the contract tests and confirm the expected RED failure.
- [ ] Add the minimal CI and Make targets.
- [ ] Run the contract tests and confirm GREEN.
- [ ] Update README and, only after full verification, mark M3A-M3F complete in
  the Stage 3 docs.
- [ ] Commit tooling and documentation.

## Task 5: Full verification and handoff

- [ ] Run frozen pnpm install, lint, typecheck, Vitest, Next build, and
  Playwright smoke locally.
- [ ] Run `make check`, all feasible PostgreSQL/Commerce/LLM/agent gates, and
  backend Docker build; record unavailable local Docker/database gates for
  hosted confirmation.
- [ ] Verify OpenAPI SHA, canonical seed fingerprint, both migration heads,
  LangGraph 1.2.11, LiteLLM v1.98.0 pin, exact five read-only tools, no Python
  migrations, and no backend production diff.
- [ ] Run `git diff --check`, inspect the final diff, and verify a clean tree.
- [ ] Push `stage3/m3f-web-chat`, open a Draft PR, wait for hosted CI, and
  report all job conclusions without merging.
