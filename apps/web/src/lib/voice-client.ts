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
  private readonly windowEventHandler: ((event: Event) => void) | null;

  constructor(options: FakeVoiceTransportOptions = {}) {
    this.options = options;
    if (options.autoEvents && typeof window !== "undefined") {
      this.windowEventHandler = (event) => {
        const detail = (event as CustomEvent<unknown>).detail;
        if (detail && typeof detail === "object") this.emit(detail as VoicePresentationEvent);
      };
      window.addEventListener("__verbaops_stage7_fake_voice_event", this.windowEventHandler);
    } else {
      this.windowEventHandler = null;
    }
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
      }, 100);
      setTimeout(() => {
        if (!this.connected) return;
        this.emit({ type: "state", state: "thinking" });
      }, 250);
      setTimeout(() => {
        if (!this.connected) return;
        this.emit({ type: "state", state: "assistant_speaking" });
      }, 400);
      setTimeout(() => {
        if (!this.connected) return;
        this.emit({ type: "state", state: "interrupted" });
      }, 550);
    }
  }

  async disconnect(): Promise<void> {
    this.connected = false;
    this.bootstrap = null;
    if (this.windowEventHandler && typeof window !== "undefined") {
      window.removeEventListener("__verbaops_stage7_fake_voice_event", this.windowEventHandler);
    }
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
  if (process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_VERBAOPS_STAGE7_FAKE_VOICE === "1") {
    return new FakeVoiceTransport({ autoEvents: true });
  }
  return createLiveKitVoiceTransport();
}
