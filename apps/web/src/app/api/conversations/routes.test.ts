import { describe, expect, it, vi } from "vitest";

import { POST as createConversation } from "./route";
import { POST as sendMessage } from "./[conversationId]/messages/route";
import { GET as getConversation } from "./[conversationId]/route";

const conversationId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";

describe("conversation BFF routes", () => {
  it("rejects identity fields without contacting the backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const response = await createConversation(
      new Request("http://web.test/api/conversations", {
        method: "POST",
        body: JSON.stringify({ customer_id: "customer" }),
      }),
    );

    expect(response.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts exactly 8000 message characters and rejects 8001", async () => {
    vi.stubEnv("VERBAOPS_API_BASE_URL", "http://verbaops.test");
    vi.stubEnv("VERBAOPS_API_TOKEN", "token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const accepted = await sendMessage(
      new Request("http://web.test", { method: "POST", body: JSON.stringify({ content: "x".repeat(8000) }) }),
      { params: Promise.resolve({ conversationId }) },
    );
    const rejected = await sendMessage(
      new Request("http://web.test", { method: "POST", body: JSON.stringify({ content: "x".repeat(8001) }) }),
      { params: Promise.resolve({ conversationId }) },
    );

    expect(accepted.status).toBe(200);
    expect(rejected.status).toBe(422);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("validates opaque conversation paths and forwards bounded pagination", async () => {
    vi.stubEnv("VERBAOPS_API_BASE_URL", "http://verbaops.test");
    vi.stubEnv("VERBAOPS_API_TOKEN", "token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ messages: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const invalid = await getConversation(
      new Request("http://web.test/api/conversations/not-a-uuid"),
      { params: Promise.resolve({ conversationId: "not-a-uuid" }) },
    );
    const valid = await getConversation(
      new Request("http://web.test/api/conversations/" + conversationId + "?limit=50&before_sequence=20"),
      { params: Promise.resolve({ conversationId }) },
    );

    expect(invalid.status).toBe(422);
    expect(valid.status).toBe(200);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      `http://verbaops.test/v1/conversations/${conversationId}?limit=50&before_sequence=20`,
    );
  });
});
