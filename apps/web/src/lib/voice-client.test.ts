import { describe, expect, it } from "vitest";

import { FakeVoiceTransport } from "./voice-client";

describe("provider-neutral voice transport", () => {
  it("publishes presentation events without an action or identity surface", async () => {
    const transport = new FakeVoiceTransport();
    const events: unknown[] = [];
    const unsubscribe = transport.subscribe((event) => events.push(event));

    await transport.connect({
      voice_session_id: "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
      conversation_id: "55fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
      livekit_url: "wss://livekit.example.test",
      room_token: "transient-token",
      token_expires_at: "2026-10-08T12:00:00.000Z",
      status: "created",
    });
    transport.emit({ type: "partial_transcript", text: "ephemeral words" });
    unsubscribe();
    transport.emit({ type: "authoritative_state_invalidated" });

    expect(events).toEqual([
      { type: "state", state: "connected" },
      { type: "state", state: "listening" },
      { type: "partial_transcript", text: "ephemeral words" },
    ]);
    expect(JSON.stringify(events)).not.toContain("role");
    expect(JSON.stringify(events)).not.toContain("customer");
    expect(JSON.stringify(events)).not.toContain("action");
  });

  it("disconnects without retaining the bootstrap token", async () => {
    const transport = new FakeVoiceTransport();
    const bootstrap = {
      voice_session_id: "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
      conversation_id: "55fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
      livekit_url: "ws://localhost:7880",
      room_token: "transient-token",
      token_expires_at: "2026-10-08T12:00:00.000Z",
      status: "created" as const,
    };

    await transport.connect(bootstrap);
    await transport.disconnect();

    expect(transport.isConnected()).toBe(false);
    expect(transport.lastBootstrap()).toBeNull();
  });
});

