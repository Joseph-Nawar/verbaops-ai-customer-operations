import { describe, expect, it, vi } from "vitest";

import { GET as getAction } from "./[actionRequestId]/route";
import { POST as approveAction } from "./[actionRequestId]/approval/route";
import { POST as rejectApproval } from "./[actionRequestId]/approval-rejection/route";
import { POST as confirmAction } from "./[actionRequestId]/confirmation/route";
import { POST as reconcileAction } from "./[actionRequestId]/reconciliation/route";
import { POST as rejectAction } from "./[actionRequestId]/rejection/route";

const actionRequestId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const fingerprint = "a".repeat(64);
const context = { params: Promise.resolve({ actionRequestId }) };

function backendResponse(body: unknown = { ok: true }, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("action request BFF routes", () => {
  it("validates UUID paths before forwarding", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await getAction(new Request("http://web.test"), {
      params: Promise.resolve({ actionRequestId: "not-a-uuid" }),
    });

    expect(response.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards the fixed GET path with no-store and server credentials", async () => {
    vi.stubEnv("VERBAOPS_API_BASE_URL", "http://verbaops.test");
    vi.stubEnv("VERBAOPS_API_TOKEN", "server-token");
    const fetchMock = vi.fn().mockResolvedValue(backendResponse({ state: "awaiting_confirmation" }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await getAction(new Request("http://web.test"), context);

    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      `http://verbaops.test/v1/action-requests/${actionRequestId}`,
    );
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("GET");
  });

  it.each([
    ["confirmation", confirmAction],
    ["rejection", rejectAction],
    ["approval", approveAction],
    ["approval rejection", rejectApproval],
  ])("accepts only the exact fingerprint body for %s", async (_name, route) => {
    vi.stubEnv("VERBAOPS_API_BASE_URL", "http://verbaops.test");
    vi.stubEnv("VERBAOPS_API_TOKEN", "server-token");
    const fetchMock = vi.fn().mockResolvedValue(backendResponse());
    vi.stubGlobal("fetch", fetchMock);

    const response = await route(
      new Request("http://web.test", {
        method: "POST",
        body: JSON.stringify({ proposal_fingerprint: fingerprint }),
      }),
      context,
    );

    expect(response.status).toBe(200);
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain(`/v1/action-requests/${actionRequestId}/`);
    expect(JSON.parse(String(options.body))).toEqual({ proposal_fingerprint: fingerprint });
  });

  it.each([
    {},
    { proposal_fingerprint: "A".repeat(64) },
    { proposal_fingerprint: "a".repeat(63) },
    { proposal_fingerprint: fingerprint, customer_id: "customer" },
    { proposal_fingerprint: fingerprint, state: "confirmed" },
    { proposal_fingerprint: fingerprint, idempotency_key: "key" },
  ])("rejects non-authoritative decision body %j", async (body) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await confirmAction(
      new Request("http://web.test", { method: "POST", body: JSON.stringify(body) }),
      context,
    );

    expect(response.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards reconciliation without a caller body and rejects supplied payloads", async () => {
    vi.stubEnv("VERBAOPS_API_BASE_URL", "http://verbaops.test");
    vi.stubEnv("VERBAOPS_API_TOKEN", "server-token");
    const fetchMock = vi.fn().mockResolvedValue(backendResponse());
    vi.stubGlobal("fetch", fetchMock);

    const accepted = await reconcileAction(new Request("http://web.test", { method: "POST" }), context);
    const rejected = await reconcileAction(
      new Request("http://web.test", { method: "POST", body: JSON.stringify({ state: "unresolved" }) }),
      context,
    );

    expect(accepted.status).toBe(200);
    expect(rejected.status).toBe(422);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      `http://verbaops.test/v1/action-requests/${actionRequestId}/reconciliation`,
    );
    expect((fetchMock.mock.calls[0][1] as RequestInit).body).toBeUndefined();
  });

  it("passes through sanitized backend status envelopes", async () => {
    vi.stubEnv("VERBAOPS_API_BASE_URL", "http://verbaops.test");
    vi.stubEnv("VERBAOPS_API_TOKEN", "server-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(backendResponse({ error: { code: "conflict", message: "conflict" } }, 409)));

    const response = await rejectAction(
      new Request("http://web.test", {
        method: "POST",
        body: JSON.stringify({ proposal_fingerprint: fingerprint }),
      }),
      context,
    );

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ error: { code: "conflict", message: "conflict" } });
  });
});
