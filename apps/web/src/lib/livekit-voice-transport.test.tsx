import { describe, expect, it, vi } from "vitest";

const roomControl = vi.hoisted(() => {
  const instances: Array<{
    connect: () => Promise<void>;
    resolveConnect: () => void;
    disconnect: () => Promise<void>;
    disconnectCalls: number;
    localParticipant: {
      identity: string;
      setMicrophoneEnabled: ReturnType<typeof vi.fn>;
    };
    on: (event: string, listener: (...args: unknown[]) => void) => void;
    emit: (event: string, ...args: unknown[]) => void;
  }> = [];

  class FakeRoom {
    private readonly listeners = new Map<string, Array<(...args: unknown[]) => void>>();
    private readonly connectPromise: Promise<void>;
    private resolveConnectPromise!: () => void;
    public disconnectCalls = 0;
    public readonly localParticipant = {
      identity: "local-customer",
      setMicrophoneEnabled: vi.fn().mockResolvedValue(undefined),
    };

    constructor() {
      this.connectPromise = new Promise<void>((resolve) => {
        this.resolveConnectPromise = resolve;
      });
      instances.push(this);
    }

    connect(): Promise<void> {
      return this.connectPromise;
    }

    resolveConnect(): void {
      this.resolveConnectPromise();
    }

    async disconnect(): Promise<void> {
      this.disconnectCalls += 1;
    }

    on(event: string, listener: (...args: unknown[]) => void): void {
      const listeners = this.listeners.get(event) ?? [];
      listeners.push(listener);
      this.listeners.set(event, listeners);
    }

    emit(event: string, ...args: unknown[]): void {
      for (const listener of this.listeners.get(event) ?? []) listener(...args);
    }
  }

  return { FakeRoom, instances };
});

vi.mock("livekit-client", () => ({
  Room: roomControl.FakeRoom,
  RoomEvent: {
    Reconnecting: "reconnecting",
    Connected: "connected",
    Disconnected: "disconnected",
    ActiveSpeakersChanged: "activeSpeakersChanged",
  },
}));

import { LiveKitVoiceTransport } from "./livekit-voice-transport";

const bootstrap = {
  voice_session_id: "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
  conversation_id: "55fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
  livekit_url: "wss://livekit.example.test",
  room_token: "transient-token",
  token_expires_at: "2026-10-08T12:00:00.000Z",
  status: "created" as const,
};

describe("LiveKitVoiceTransport", () => {
  it("test_cancel_during_pending_transport_connect_does_not_enable_microphone", async () => {
    const transport = new LiveKitVoiceTransport();
    const connecting = transport.connect(bootstrap);
    const room = roomControl.instances.at(-1);

    expect(room).toBeDefined();
    await transport.disconnect();
    room?.resolveConnect();
    await connecting;

    expect(room?.localParticipant.setMicrophoneEnabled).not.toHaveBeenCalled();
    expect(room?.disconnectCalls).toBe(2);
  });

  it("classifies only the local participant as user speaking", async () => {
    const transport = new LiveKitVoiceTransport();
    const events: string[] = [];
    transport.subscribe((event) => {
      if (event.type === "state") events.push(event.state);
    });
    const connecting = transport.connect(bootstrap);
    const room = roomControl.instances.at(-1);
    expect(room).toBeDefined();
    room?.resolveConnect();
    await connecting;

    room?.emit("activeSpeakersChanged", [room.localParticipant]);
    expect(events.at(-1)).toBe("user_speaking");

    room?.emit("activeSpeakersChanged", [{ identity: "remote-agent" }]);
    expect(events.at(-1)).toBe("listening");
    expect(events).not.toContain("assistant_speaking");

    room?.emit("activeSpeakersChanged", []);
    expect(events.at(-1)).toBe("listening");
    await transport.disconnect();
  });
});
