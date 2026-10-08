"use client";

import type { ReactNode } from "react";

import type { VoiceSessionBootstrap } from "./voice-contract";
import { createLiveKitVoiceTransport } from "./livekit-voice-transport";

export type VoiceConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "listening"
  | "user_speaking"
  | "thinking"
  | "assistant_speaking"
  | "interrupted"
  | "error";

export type VoicePresentationEvent =
  | { type: "state"; state: VoiceConnectionState }
  | { type: "partial_transcript"; text: string }
  | { type: "authoritative_state_invalidated" }
  | { type: "error"; message: string };

export type VoicePresentationListener = (event: VoicePresentationEvent) => void;

export interface VoiceTransport {
  connect(bootstrap: VoiceSessionBootstrap): Promise<void>;
  disconnect(): Promise<void>;
  subscribe(listener: VoicePresentationListener): () => void;
  renderAudio?(): ReactNode;
}

export type FakeVoiceTransportOptions = {
  connectError?: Error;
  autoEvents?: boolean;
};

export class FakeVoiceTransport implements VoiceTransport {
  private readonly listeners = new Set<VoicePresentationListener>();
  private readonly options: FakeVoiceTransportOptions;
  private connected = false;
  private bootstrap: VoiceSessionBootstrap | null = null;

  constructor(options: FakeVoiceTransportOptions = {}) {
    this.options = options;
  }

  async connect(bootstrap: VoiceSessionBootstrap): Promise<void> {
    if (this.options.connectError) throw this.options.connectError;
    this.bootstrap = bootstrap;
    this.connected = true;
    this.emit({ type: "state", state: "connected" });
    this.emit({ type: "state", state: "listening" });
    if (this.options.autoEvents) {
      setTimeout(() => {
        if (!this.connected) return;
        this.emit({ type: "partial_transcript", text: "Fake partial transcript" });
        this.emit({ type: "state", state: "user_speaking" });
      }, 20);
      setTimeout(() => {
        if (!this.connected) return;
        this.emit({ type: "state", state: "thinking" });
      }, 40);
      setTimeout(() => {
        if (!this.connected) return;
        this.emit({ type: "state", state: "assistant_speaking" });
      }, 60);
      setTimeout(() => {
        if (!this.connected) return;
        this.emit({ type: "state", state: "interrupted" });
      }, 80);
    }
  }

  async disconnect(): Promise<void> {
    this.connected = false;
    this.bootstrap = null;
    this.emit({ type: "state", state: "disconnected" });
  }

  subscribe(listener: VoicePresentationListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(event: VoicePresentationEvent): void {
    for (const listener of this.listeners) listener(event);
  }

  isConnected(): boolean {
    return this.connected;
  }

  lastBootstrap(): VoiceSessionBootstrap | null {
    return this.bootstrap;
  }
}

export function createVoiceTransport(): VoiceTransport {
  if (process.env.NEXT_PUBLIC_VERBAOPS_STAGE7_FAKE_VOICE === "1") {
    return new FakeVoiceTransport({ autoEvents: true });
  }
  return createLiveKitVoiceTransport();
}

