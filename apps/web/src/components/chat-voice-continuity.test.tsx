import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Chat } from "./chat";

const conversationId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const voiceSessionId = "55fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const bootstrap = {
  voice_session_id: voiceSessionId,
  conversation_id: conversationId,
  livekit_url: "wss://livekit.example.test",
  room_token: "transient-token",
  token_expires_at: "2026-10-08T12:00:00.000Z",
  status: "created",
};

function voiceResponse(): Response {
  return new Response(JSON.stringify(bootstrap), { status: 201 });
}

describe("Chat and browser voice conversation continuity", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.stubEnv("NEXT_PUBLIC_VERBAOPS_STAGE7_FAKE_VOICE", "1");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("reuses a text-created conversation when voice starts", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ conversation_id: conversationId }), { status: 201 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            conversation_id: conversationId,
            user_message: { id: "user-1", role: "user", content: "hello" },
            assistant_message: { id: "assistant-1", role: "assistant", content: "Hi" },
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(voiceResponse());
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await user.type(screen.getByLabelText("Message"), "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Hi");
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    await screen.findByText("Voice connected");

    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/voice/sessions",
      expect.objectContaining({ body: JSON.stringify({ conversation_id: conversationId }) }),
    );
    expect(sessionStorage.getItem("verbaops.conversationId")).toBe(conversationId);
  });

  it("reuses a voice-created conversation for the next text turn", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(voiceResponse())
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            conversation_id: conversationId,
            user_message: { id: "user-1", role: "user", content: "follow up" },
            assistant_message: { id: "assistant-1", role: "assistant", content: "Follow-up answer" },
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    await screen.findByText("Voice connected");
    await user.type(screen.getByLabelText("Message"), "follow up");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Follow-up answer");

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `/api/conversations/${conversationId}/messages`,
      expect.objectContaining({ body: JSON.stringify({ content: "follow up" }) }),
    );
  });

  it("reloads the conversation identifier without restoring a voice session or token", async () => {
    sessionStorage.setItem("verbaops.conversationId", conversationId);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ messages: [], active_action_requests: [] }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await screen.findByText("Ask about an order, shipment, refund, product, or delivery slot.");

    expect(screen.getByText("Voice disconnected")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/voice/sessions", expect.anything());
    expect(Object.keys(sessionStorage)).toEqual(["verbaops.conversationId"]);
  });

  it("ends and clears the voice session while preserving no conversation after New conversation", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValueOnce(voiceResponse()).mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ended" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    await screen.findByText("Voice connected");
    await user.click(screen.getByRole("button", { name: "New conversation" }));

    await waitFor(() => expect(screen.getByText("Voice disconnected")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenNthCalledWith(2, `/api/voice/sessions/${voiceSessionId}/end`, expect.any(Object));
    expect(sessionStorage.getItem("verbaops.conversationId")).toBeNull();
    expect(screen.getByText("Voice disconnected")).toBeInTheDocument();
  });
});

