import { act, render, screen, waitFor } from "@testing-library/react";
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

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
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

  it("serializes initial text creation before voice bootstrap", async () => {
    const user = userEvent.setup();
    const pendingConversation = deferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/conversations") return pendingConversation.promise;
      if (url === `/api/conversations/${conversationId}/messages`) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              conversation_id: conversationId,
              user_message: { id: "user-1", role: "user", content: "hello" },
              assistant_message: { id: "assistant-1", role: "assistant", content: "Hi" },
            }),
            { status: 200 },
          ),
        );
      }
      if (url === "/api/voice/sessions") return Promise.resolve(voiceResponse());
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await user.type(screen.getByLabelText("Message"), "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: "Start voice" }));
    expect(fetchMock).not.toHaveBeenCalledWith("/api/voice/sessions", expect.anything());

    await act(async () => {
      pendingConversation.resolve(new Response(JSON.stringify({ conversation_id: conversationId }), { status: 201 }));
      await pendingConversation.promise;
    });
    expect(await screen.findByText("Hi")).toBeInTheDocument();
    await screen.findByText("Voice connected");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/voice/sessions",
      expect.objectContaining({ body: JSON.stringify({ conversation_id: conversationId }) }),
    );
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/conversations")).toHaveLength(1);
  });

  it("serializes initial voice bootstrap before text creation", async () => {
    const user = userEvent.setup();
    const pendingVoice = deferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/voice/sessions") return pendingVoice.promise;
      if (url === `/api/conversations/${conversationId}/messages`) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              conversation_id: conversationId,
              user_message: { id: "user-1", role: "user", content: "follow up" },
              assistant_message: { id: "assistant-1", role: "assistant", content: "Follow-up answer" },
            }),
            { status: 200 },
          ),
        );
      }
      if (url === "/api/conversations") {
        throw new Error(`competing conversation creation: ${init?.method ?? "GET"}`);
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await user.type(screen.getByLabelText("Message"), "follow up");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(fetchMock).not.toHaveBeenCalledWith("/api/conversations", expect.anything());

    await act(async () => {
      pendingVoice.resolve(voiceResponse());
      await pendingVoice.promise;
    });
    expect(await screen.findByText("Follow-up answer")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/conversations", expect.anything());
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/conversations/${conversationId}/messages`,
      expect.objectContaining({ body: JSON.stringify({ content: "follow up" }) }),
    );
  });

  it("does not apply a late voice refresh after New conversation resets Chat", async () => {
    const user = userEvent.setup();
    const pendingRefresh = deferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/voice/sessions") return Promise.resolve(voiceResponse());
      if (url === `/api/voice/sessions/${voiceSessionId}/end`) {
        return Promise.resolve(new Response(JSON.stringify({ status: "ended" }), { status: 200 }));
      }
      if (url === `/api/conversations/${conversationId}`) return pendingRefresh.promise;
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    await screen.findByText("Voice connected");
    window.dispatchEvent(
      new CustomEvent("__verbaops_stage7_fake_voice_event", {
        detail: { type: "authoritative_state_invalidated" },
      }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(`/api/conversations/${conversationId}`, expect.any(Object)));

    await user.click(screen.getByRole("button", { name: "New conversation" }));
    await screen.findByText("Voice disconnected");
    await act(async () => {
      pendingRefresh.resolve(
        new Response(
          JSON.stringify({
            messages: [{ id: "stale", role: "assistant", content: "stale assistant response" }],
            active_action_requests: [],
          }),
          { status: 200 },
        ),
      );
      await pendingRefresh.promise;
    });

    expect(screen.queryByText("stale assistant response")).not.toBeInTheDocument();
    expect(screen.getByText("Ask about an order, shipment, refund, product, or delivery slot.")).toBeInTheDocument();
  });
});
