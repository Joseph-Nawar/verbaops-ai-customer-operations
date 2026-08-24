import { describe, expect, it, vi } from "vitest";

import { forwardToVerbaOps } from "./verbaops";

describe("VerbaOps server BFF helper", () => {
  it("injects the bearer, disables caching, and forwards JSON safely", async () => {
    vi.stubEnv("VERBAOPS_API_BASE_URL", "http://verbaops.test/");
    vi.stubEnv("VERBAOPS_API_TOKEN", "server-secret-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ conversation_id: "abc" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await forwardToVerbaOps("v1/conversations", {
      method: "POST",
      body: JSON.stringify({}),
    });

    expect(result.status).toBe(201);
    expect(await result.json()).toEqual({ conversation_id: "abc" });
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toBe("http://verbaops.test/v1/conversations");
    expect(options.cache).toBe("no-store");
    expect(new Headers(options.headers).get("accept")).toBe("application/json");
    expect(new Headers(options.headers).get("authorization")).toBe("Bearer server-secret-token");
    expect(new Headers(options.headers).get("content-type")).toBe("application/json");
  });

  it("returns a generic safe response for network failures", async () => {
    vi.stubEnv("VERBAOPS_API_BASE_URL", "http://verbaops.test");
    vi.stubEnv("VERBAOPS_API_TOKEN", "server-secret-token");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("server-secret-token leaked")));

    const result = await forwardToVerbaOps("v1/conversations", { method: "GET" });

    expect(result.status).toBe(503);
    expect(await result.json()).toEqual({
      error: { code: "backend_unavailable", message: "The service is temporarily unavailable." },
    });
  });

  it("preserves safe backend errors while redacting a credential if one is returned", async () => {
    vi.stubEnv("VERBAOPS_API_BASE_URL", "http://verbaops.test");
    vi.stubEnv("VERBAOPS_API_TOKEN", "server-secret-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "agent_unavailable", message: "server-secret-token" } }),
          { status: 503 },
        ),
      ),
    );

    const result = await forwardToVerbaOps("v1/conversations", { method: "GET" });

    expect(result.status).toBe(503);
    expect(await result.json()).toEqual({
      error: { code: "agent_unavailable", message: "[redacted]" },
    });
  });
});
