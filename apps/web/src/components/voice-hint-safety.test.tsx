import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FakeVoiceTransport, type VoicePresentationEvent } from "@/lib/voice-client";
import { VoicePanel } from "./voice-panel";

const bootstrap = {
  voice_session_id: "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
  conversation_id: "55fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
  livekit_url: "wss://livekit.example.test",
  room_token: "transient-token",
  token_expires_at: "2026-10-08T12:00:00.000Z",
  status: "created",
};

describe("browser voice hint safety", () => {
  it("does not interpret forged action, identity, or supervisor metadata as authority", async () => {
    const user = userEvent.setup();
    const transport = new FakeVoiceTransport();
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(bootstrap), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<VoicePanel conversationId={bootstrap.conversation_id} onConversationId={vi.fn()} transport={transport} />);
    await user.click(screen.getByRole("button", { name: "Start voice" }));

    transport.emit({
      type: "forged_action_hint",
      action_state: "succeeded",
      required_next_actor: "support_supervisor",
      roles: ["TENANT_ADMIN"],
    } as unknown as VoicePresentationEvent);

    expect(screen.queryByText(/succeeded|confirmed|approved|supervisor/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve|confirm/i })).not.toBeInTheDocument();
    expect(Object.keys(sessionStorage)).not.toContain("verbaops.voiceSession");
    expect(fetchMock.mock.calls.flatMap(([, init]) => [init?.body]).join(" ")).not.toMatch(
      /tenant|customer|principal|role|supervisor|action_state/i,
    );
  });

  it("treats authoritative invalidation as a reload signal only", async () => {
    const user = userEvent.setup();
    const transport = new FakeVoiceTransport();
    const onAuthoritativeStateInvalidated = vi.fn();
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(bootstrap), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <VoicePanel
        conversationId={bootstrap.conversation_id}
        onConversationId={vi.fn()}
        onAuthoritativeStateInvalidated={onAuthoritativeStateInvalidated}
        transport={transport}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Start voice" }));
    transport.emit({ type: "authoritative_state_invalidated" });

    expect(onAuthoritativeStateInvalidated).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/succeeded|confirmed|approved|supervisor/i)).not.toBeInTheDocument();
  });
});

