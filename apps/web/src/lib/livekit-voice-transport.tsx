"use client";

import { Room, RoomEvent } from "livekit-client";
import { RoomAudioRenderer } from "@livekit/components-react";
import type { ReactNode } from "react";

import type { VoiceSessionBootstrap } from "./voice-contract";
import type { VoicePresentationEvent, VoicePresentationListener, VoiceTransport } from "./voice-client";

export class LiveKitVoiceTransport implements VoiceTransport {
  private readonly listeners = new Set<VoicePresentationListener>();
  private room: Room | null = null;

  async connect(bootstrap: VoiceSessionBootstrap): Promise<void> {
    if (this.room) await this.disconnect();
    const room = new Room({ adaptiveStream: true });
    this.room = room;
    room.on(RoomEvent.Reconnecting, () => this.emit({ type: "state", state: "connecting" }));
    room.on(RoomEvent.Connected, () => this.emit({ type: "state", state: "connected" }));
    room.on(RoomEvent.Disconnected, () => this.emit({ type: "state", state: "disconnected" }));
    room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
      this.emit({ type: "state", state: speakers.length > 0 ? "user_speaking" : "listening" });
    });

    try {
      await room.connect(bootstrap.livekit_url, bootstrap.room_token);
      await room.localParticipant.setMicrophoneEnabled(true);
      this.emit({ type: "state", state: "listening" });
    } catch {
      await room.disconnect(true).catch(() => undefined);
      this.room = null;
      this.emit({ type: "error", message: "Voice is temporarily unavailable." });
      throw new Error("voice_connection_failed");
    }
  }

  async disconnect(): Promise<void> {
    const room = this.room;
    this.room = null;
    if (room) await room.disconnect(true);
  }

  subscribe(listener: VoicePresentationListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  renderAudio(): ReactNode {
    return this.room ? <RoomAudioRenderer room={this.room} /> : null;
  }

  private emit(event: VoicePresentationEvent): void {
    for (const listener of this.listeners) listener(event);
  }
}

export function createLiveKitVoiceTransport(): VoiceTransport {
  return new LiveKitVoiceTransport();
}

