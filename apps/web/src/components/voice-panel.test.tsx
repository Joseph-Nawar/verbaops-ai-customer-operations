import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRef } from "react";

import { FakeVoiceTransport } from "@/lib/voice-client";
import { VoicePanel } from "./voice-panel";

const voiceSessionId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const existingConversationId = "55fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const createdConversationId = "65fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";

const bootstrap = {
  voice_session_id: voiceSessionId,
  conversation_id: createdConversationId,
  livekit_url: "wss://livekit.example.test",
  room_token: "secret-transient-token",
  token_expires_at: "2026-10-08T12:00:00.000Z",
  status: "created",
};

function startResponse(): Response {
  return new Response(JSON.stringify(bootstrap), { status: 201 });
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("VoicePanel", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("starts with the existing conversation, connects, and stores only its conversation id", async () => {
    const user = userEvent.setup();
    const transport = new FakeVoiceTransport();
    const fetchMock = vi.fn().mockResolvedValueOnce(startResponse()).mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ended" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<VoicePanel conversationId={existingConversationId} onConversationId={vi.fn()} transport={transport} />);
    await user.click(screen.getByRole("button", { name: "Start voice" }));

    expect(await screen.findByText("Voice connected")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/voice/sessions",
      expect.objectContaining({ body: JSON.stringify({ conversation_id: existingConversationId }) }),
    );
    expect(sessionStorage.getItem("verbaops.conversationId")).toBe(createdConversationId);
    expect(Object.keys(sessionStorage)).toEqual(["verbaops.conversationId"]);
    expect(document.body).not.toHaveTextContent("secret-transient-token");

    transport.emit({ type: "partial_transcript", text: "temporary transcript" });
    expect(await screen.findByText("temporary transcript")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "End voice" }));
    await waitFor(() => expect(screen.getByText("Voice disconnected")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `/api/voice/sessions/${voiceSessionId}/end`,
      expect.not.objectContaining({ body: expect.anything() }),
    );
    expect(sessionStorage.getItem("verbaops.conversationId")).toBe(createdConversationId);
  });

  it("adopts and persists a server-created conversation", async () => {
    const user = userEvent.setup();
    const transport = new FakeVoiceTransport();
    const onConversationId = vi.fn();
    const fetchMock = vi.fn().mockResolvedValueOnce(startResponse());
    vi.stubGlobal("fetch", fetchMock);

    render(<VoicePanel conversationId={null} onConversationId={onConversationId} transport={transport} />);
    await user.click(screen.getByRole("button", { name: "Start voice" }));

    expect(onConversationId).toHaveBeenCalledWith(createdConversationId);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/voice/sessions",
      expect.objectContaining({ body: "{}" }),
    );
    expect(sessionStorage.getItem("verbaops.conversationId")).toBe(createdConversationId);
  });

  it("ends a session after connect failure and exposes a bounded error", async () => {
    const user = userEvent.setup();
    const transport = new FakeVoiceTransport({ connectError: new Error("provider detail") });
    const fetchMock = vi.fn().mockResolvedValueOnce(startResponse()).mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ended" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<VoicePanel conversationId={existingConversationId} onConversationId={vi.fn()} transport={transport} />);
    await user.click(screen.getByRole("button", { name: "Start voice" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Voice is temporarily unavailable.");
    expect(screen.getByRole("button", { name: "Start voice" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(2, `/api/voice/sessions/${voiceSessionId}/end`, expect.any(Object));
    expect(document.body).not.toHaveTextContent("provider detail");
  });

  it("refreshes authoritative state when the transport reports invalidation", async () => {
    const transport = new FakeVoiceTransport();
    const onAuthoritativeStateInvalidated = vi.fn();
    const fetchMock = vi.fn().mockResolvedValueOnce(startResponse());
    vi.stubGlobal("fetch", fetchMock);

    render(
      <VoicePanel
        conversationId={existingConversationId}
        onConversationId={vi.fn()}
        onAuthoritativeStateInvalidated={onAuthoritativeStateInvalidated}
        transport={transport}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    transport.emit({ type: "authoritative_state_invalidated" });

    expect(onAuthoritativeStateInvalidated).toHaveBeenCalledTimes(1);
  });

  it("test_new_conversation_during_pending_bootstrap_does_not_resurrect_voice", async () => {
    const user = userEvent.setup();
    const panelRef = createRef<{ resetVoiceSession: () => Promise<void> }>();
    const pendingBootstrap = deferred<Response>();
    const transport = new FakeVoiceTransport();
    const connectSpy = vi.spyOn(transport, "connect");
    const fetchMock = vi.fn().mockReturnValueOnce(pendingBootstrap.promise).mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ended" }), { status: 200 }),
    );
    const onConversationId = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <VoicePanel
        ref={panelRef}
        conversationId={null}
        onConversationId={onConversationId}
        transport={transport}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await panelRef.current?.resetVoiceSession();
    await act(async () => {
      pendingBootstrap.resolve(startResponse());
      await pendingBootstrap.promise;
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `/api/voice/sessions/${voiceSessionId}/end`,
      expect.any(Object),
    );
    expect(onConversationId).not.toHaveBeenCalled();
    expect(connectSpy).not.toHaveBeenCalled();
    expect(transport.isConnected()).toBe(false);
    expect(sessionStorage.getItem("verbaops.conversationId")).toBeNull();
    expect(screen.getByText("Voice disconnected")).toBeInTheDocument();
  });

  it("test_unmount_during_pending_bootstrap_ends_late_session", async () => {
    const user = userEvent.setup();
    const pendingBootstrap = deferred<Response>();
    const transport = new FakeVoiceTransport();
    const connectSpy = vi.spyOn(transport, "connect");
    const fetchMock = vi.fn().mockReturnValueOnce(pendingBootstrap.promise).mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ended" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = render(
      <VoicePanel conversationId={null} onConversationId={vi.fn()} transport={transport} />,
    );
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    unmount();
    await act(async () => {
      pendingBootstrap.resolve(startResponse());
      await pendingBootstrap.promise;
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `/api/voice/sessions/${voiceSessionId}/end`,
      expect.any(Object),
    );
    expect(connectSpy).not.toHaveBeenCalled();
    expect(transport.isConnected()).toBe(false);
  });

  it("test_cancelled_bootstrap_does_not_restore_conversation_storage", async () => {
    const user = userEvent.setup();
    const panelRef = createRef<{ resetVoiceSession: () => Promise<void> }>();
    const pendingBootstrap = deferred<Response>();
    const transport = new FakeVoiceTransport();
    const connectSpy = vi.spyOn(transport, "connect");
    const fetchMock = vi.fn().mockReturnValueOnce(pendingBootstrap.promise).mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ended" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <VoicePanel
        ref={panelRef}
        conversationId={null}
        onConversationId={vi.fn()}
        transport={transport}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    await panelRef.current?.resetVoiceSession();
    await act(async () => {
      pendingBootstrap.resolve(startResponse());
      await pendingBootstrap.promise;
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(connectSpy).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("verbaops.conversationId")).toBeNull();
    expect(transport.lastBootstrap()).toBeNull();
  });

  it("test_start_after_cancelled_bootstrap_can_succeed", async () => {
    const user = userEvent.setup();
    const panelRef = createRef<{ resetVoiceSession: () => Promise<void> }>();
    const pendingBootstrap = deferred<Response>();
    const transport = new FakeVoiceTransport();
    const connectSpy = vi.spyOn(transport, "connect");
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(pendingBootstrap.promise)
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "ended" }), { status: 200 }))
      .mockResolvedValueOnce(startResponse());
    vi.stubGlobal("fetch", fetchMock);

    render(
      <VoicePanel
        ref={panelRef}
        conversationId={null}
        onConversationId={vi.fn()}
        transport={transport}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    await panelRef.current?.resetVoiceSession();
    await act(async () => {
      pendingBootstrap.resolve(startResponse());
      await pendingBootstrap.promise;
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole("button", { name: "Start voice" }));
    expect(await screen.findByText("Voice connected")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/voice/sessions", expect.any(Object));
    expect(connectSpy).toHaveBeenCalledTimes(1);
    expect(transport.isConnected()).toBe(true);
  });
});
