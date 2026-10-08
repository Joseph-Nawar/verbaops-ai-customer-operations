"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import {
  createVoiceTransport,
  type VoiceConnectionState,
  type VoicePresentationEvent,
  type VoiceTransport,
} from "@/lib/voice-client";
import { isVoiceSessionBootstrap } from "@/lib/voice-contract";

export type VoicePanelHandle = {
  resetVoiceSession: () => Promise<void>;
};

type VoicePanelProps = {
  conversationId: string | null;
  onConversationId: (conversationId: string) => void;
  onAuthoritativeStateInvalidated?: () => void;
  transport?: VoiceTransport;
};

function stateLabel(state: VoiceConnectionState): string {
  switch (state) {
    case "connecting":
      return "Connecting voice";
    case "connected":
    case "listening":
      return "Voice connected";
    case "user_speaking":
      return "Listening to you";
    case "thinking":
      return "Thinking";
    case "assistant_speaking":
      return "Assistant speaking";
    case "interrupted":
      return "Assistant interrupted";
    case "error":
      return "Voice unavailable";
    case "disconnected":
      return "Voice disconnected";
  }
}

async function readBootstrap(response: Response) {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok || !isVoiceSessionBootstrap(body)) throw new Error("voice_unavailable");
  return body;
}

export const VoicePanel = forwardRef<VoicePanelHandle, VoicePanelProps>(function VoicePanel(
  { conversationId, onConversationId, onAuthoritativeStateInvalidated, transport: providedTransport },
  ref,
) {
  const transportRef = useRef<VoiceTransport | null>(providedTransport ?? null);
  if (transportRef.current === null) transportRef.current = providedTransport ?? createVoiceTransport();
  const sessionIdRef = useRef<string | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const endingRef = useRef(false);
  const mountedRef = useRef(true);
  const invalidatedCallbackRef = useRef(onAuthoritativeStateInvalidated);
  const terminateRef = useRef<() => Promise<void>>(() => Promise.resolve());
  const [state, setState] = useState<VoiceConnectionState>("disconnected");
  const [partialTranscript, setPartialTranscript] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  invalidatedCallbackRef.current = onAuthoritativeStateInvalidated;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      void terminateRef.current();
    };
  }, []);

  function handlePresentationEvent(event: VoicePresentationEvent): void {
    if (event.type === "state") {
      if (mountedRef.current) setState(event.state);
      return;
    }
    if (event.type === "partial_transcript") {
      if (mountedRef.current) setPartialTranscript(event.text);
      return;
    }
    if (event.type === "authoritative_state_invalidated") {
      invalidatedCallbackRef.current?.();
      return;
    }
    if (event.type === "error" && mountedRef.current) {
      setError(true);
      setState("error");
    }
  }

  async function endVoiceSession(): Promise<void> {
    if (endingRef.current) return;
    const sessionId = sessionIdRef.current;
    if (!sessionId && state === "disconnected") return;
    endingRef.current = true;
    setBusy(true);
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    try {
      await transportRef.current?.disconnect();
    } catch {
      // Local teardown remains bounded even if the transport is already gone.
    }
    if (sessionId) {
      try {
        await fetch(`/api/voice/sessions/${encodeURIComponent(sessionId)}/end`, {
          method: "POST",
          headers: { accept: "application/json" },
          cache: "no-store",
        });
      } catch {
        // End is best effort; the server session lifecycle remains authoritative.
      }
    }
    sessionIdRef.current = null;
    endingRef.current = false;
    if (mountedRef.current) {
      setPartialTranscript("");
      setState("disconnected");
      setBusy(false);
    }
  }

  terminateRef.current = endVoiceSession;
  useImperativeHandle(ref, () => ({ resetVoiceSession: endVoiceSession }));

  async function startVoiceSession(): Promise<void> {
    if (busy || sessionIdRef.current) return;
    setBusy(true);
    setError(false);
    setPartialTranscript("");
    setState("connecting");
    try {
      const response = await fetch("/api/voice/sessions", {
        method: "POST",
        headers: { accept: "application/json", "content-type": "application/json" },
        body: JSON.stringify(conversationId ? { conversation_id: conversationId } : {}),
        cache: "no-store",
      });
      const bootstrap = await readBootstrap(response);
      sessionIdRef.current = bootstrap.voice_session_id;
      onConversationId(bootstrap.conversation_id);
      try {
        sessionStorage.setItem("verbaops.conversationId", bootstrap.conversation_id);
      } catch {
        // Storage is optional; the server remains authoritative.
      }
      unsubscribeRef.current = transportRef.current?.subscribe(handlePresentationEvent) ?? null;
      await transportRef.current?.connect(bootstrap);
      if (mountedRef.current) setState("listening");
    } catch {
      await endVoiceSession();
      if (mountedRef.current) {
        setError(true);
        setState("error");
      }
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }

  const connected = state !== "disconnected" && state !== "error";
  return (
    <section className="voice-panel" aria-label="Browser voice">
      <div className="voice-panel-header">
        <div>
          <p className="eyebrow">Browser voice</p>
          <p className="voice-status" aria-live="polite" data-voice-state={state}>
            {stateLabel(state)}
          </p>
        </div>
        <button
          className={connected ? "secondary-button" : "send-button"}
          type="button"
          onClick={() => void (connected ? endVoiceSession() : startVoiceSession())}
          disabled={busy}
        >
          {connected ? "End voice" : "Start voice"}
        </button>
      </div>
      {partialTranscript ? (
        <p className="voice-partial" aria-label="Live transcript">
          {partialTranscript}
        </p>
      ) : null}
      {error ? <p className="error-row" role="alert">Voice is temporarily unavailable.</p> : null}
      {transportRef.current?.renderAudio?.()}
    </section>
  );
});
