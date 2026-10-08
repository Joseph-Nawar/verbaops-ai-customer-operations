"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";

import {
  ActionRequestCard,
  isActionRequestView,
  loadActionView,
  type ActionRequestView,
} from "./action-request-card";
import { VoicePanel, type VoicePanelHandle } from "./voice-panel";
import { isConversationId } from "@/lib/server/request-validation";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type MessageResponse = {
  conversation_id: string;
  user_message: Message;
  assistant_message: Message;
  action_requests?: Array<{ action_request_id: string }>;
};

type ConversationResponse = {
  messages: Message[];
  active_action_requests: ActionRequestView[];
};

async function readApiResponse(response: Response): Promise<Record<string, unknown>> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok || typeof body !== "object" || body === null) {
    const error = new Error("request_failed") as Error & { status: number };
    error.status = response.status;
    throw error;
  }
  return body as Record<string, unknown>;
}

function isMessage(value: unknown): value is Message {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    typeof (value as Record<string, unknown>).id === "string" &&
    ((value as Record<string, unknown>).role === "user" ||
      (value as Record<string, unknown>).role === "assistant") &&
    typeof (value as Record<string, unknown>).content === "string"
  );
}

async function loadConversation(conversationId: string): Promise<ConversationResponse> {
  const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "GET",
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  const body = await readApiResponse(response);
  if (
    !Array.isArray(body.messages) ||
    !body.messages.every(isMessage) ||
    !Array.isArray(body.active_action_requests) ||
    !body.active_action_requests.every(isActionRequestView)
  ) {
    throw new Error("request_failed");
  }
  return {
    messages: body.messages,
    active_action_requests: body.active_action_requests,
  };
}

async function createConversation(): Promise<string> {
  const response = await fetch("/api/conversations", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: "{}",
    cache: "no-store",
  });
  const body = await readApiResponse(response);
  if (typeof body.conversation_id !== "string") throw new Error("request_failed");
  return body.conversation_id;
}

async function sendMessage(conversationId: string, content: string): Promise<MessageResponse> {
  const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ content }),
    cache: "no-store",
  });
  const body = await readApiResponse(response);
  if (
    typeof body.conversation_id !== "string" ||
    typeof body.user_message !== "object" ||
    body.user_message === null ||
    typeof body.assistant_message !== "object" ||
    body.assistant_message === null
  ) {
    throw new Error("request_failed");
  }
  const actionRequests = Array.isArray(body.action_requests)
    ? body.action_requests.filter(
        (item): item is { action_request_id: string } =>
          typeof item === "object" &&
          item !== null &&
          typeof (item as Record<string, unknown>).action_request_id === "string",
      )
    : [];
  return { ...(body as unknown as MessageResponse), action_requests: actionRequests };
}

async function loadTurnActionViews(
  actionRequests: Array<{ action_request_id: string }>,
): Promise<ActionRequestView[]> {
  const bounded = actionRequests.slice(0, 6);
  const results = await Promise.all(
    bounded.map(async (summary) => {
      try {
        return await loadActionView(summary.action_request_id);
      } catch {
        return null;
      }
    }),
  );
  return results.filter((result): result is ActionRequestView => result !== null);
}

function mergeActionViews(current: ActionRequestView[], updates: ActionRequestView[]): ActionRequestView[] {
  const merged = new Map(current.map((action) => [action.action_request_id, action]));
  for (const update of updates) merged.set(update.action_request_id, update);
  return [...merged.values()];
}

export function Chat(): React.JSX.Element {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [actionRequests, setActionRequests] = useState<ActionRequestView[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const [lastFailedContent, setLastFailedContent] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const voicePanelRef = useRef<VoicePanelHandle | null>(null);

  useEffect(() => {
    let cancelled = false;
    let storedConversationId: string | null = null;
    try {
      storedConversationId = sessionStorage.getItem("verbaops.conversationId");
    } catch {
      storedConversationId = null;
    }
    if (!storedConversationId) return () => undefined;
    if (!isConversationId(storedConversationId)) {
      try {
        sessionStorage.removeItem("verbaops.conversationId");
      } catch {
        // Storage is optional; the server remains authoritative.
      }
      return () => undefined;
    }
    void loadConversation(storedConversationId)
      .then((result) => {
        if (cancelled) return;
        setConversationId(storedConversationId);
        setMessages(result.messages);
        setActionRequests(result.active_action_requests);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof Error && "status" in error && error.status === 404) {
          try {
            sessionStorage.removeItem("verbaops.conversationId");
          } catch {
            // Storage is optional.
          }
          setConversationId(null);
          return;
        }
        setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submitContent(content: string): Promise<void> {
    const cleanContent = content.trim();
    if (!cleanContent || pending) return;
    setPending(true);
    setError(false);
    setLastFailedContent(cleanContent);
    try {
      const id = conversationId ?? (await createConversation());
      if (!conversationId) {
        setConversationId(id);
        try {
          sessionStorage.setItem("verbaops.conversationId", id);
        } catch {
          // Storage is optional; the server remains authoritative.
        }
      }
      const result = await sendMessage(id, cleanContent);
      setMessages((current) => [...current, result.user_message, result.assistant_message]);
      if (result.action_requests && result.action_requests.length > 0) {
        const views = await loadTurnActionViews(result.action_requests);
        setActionRequests((current) => mergeActionViews(current, views));
      }
      setDraft("");
      setLastFailedContent(null);
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    void submitContent(draft);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      formRef.current?.requestSubmit();
    }
  }

  async function refreshConversation(): Promise<void> {
    if (!conversationId) return;
    try {
      const result = await loadConversation(conversationId);
      setMessages(result.messages);
      setActionRequests(result.active_action_requests);
    } catch {
      setError(true);
    }
  }

  async function reset(): Promise<void> {
    await voicePanelRef.current?.resetVoiceSession();
    setConversationId(null);
    setMessages([]);
    setDraft("");
    setError(false);
    setLastFailedContent(null);
    setActionRequests([]);
    try {
      sessionStorage.removeItem("verbaops.conversationId");
    } catch {
      // Storage is optional; the server remains authoritative.
    }
  }

  return (
    <main className="chat-shell">
      <section className="chat-card" aria-labelledby="chat-title">
        <header className="chat-header">
          <div>
            <p className="eyebrow">NovaCommerce support</p>
            <h1 id="chat-title">VerbaOps AI</h1>
            <p className="subtitle">Customer operations with server-owned action status.</p>
          </div>
          <button className="secondary-button" type="button" onClick={() => void reset()}>
            New conversation
          </button>
        </header>

        <VoicePanel
          ref={voicePanelRef}
          conversationId={conversationId}
          onConversationId={setConversationId}
          onAuthoritativeStateInvalidated={() => void refreshConversation()}
        />

        <div className="message-list" aria-live="polite" aria-label="Conversation history">
          {messages.length === 0 ? (
            <p className="empty-state">Ask about an order, shipment, refund, product, or delivery slot.</p>
          ) : (
            messages.map((message) => (
              <article className={`message ${message.role}`} key={message.id}>
                <span className="message-label">{message.role === "user" ? "You" : "VerbaOps AI"}</span>
                <p>{message.content}</p>
              </article>
            ))
          )}
        </div>

        {actionRequests.length > 0 ? (
          <section className="action-list" aria-label="Action requests">
            {actionRequests.map((actionRequest) => (
              <ActionRequestCard
                actionRequest={actionRequest}
                key={actionRequest.action_request_id}
                onUpdated={(updated) =>
                  setActionRequests((current) => mergeActionViews(current, [updated]))
                }
              />
            ))}
          </section>
        ) : null}

        {conversationId ? <p className="conversation-id">Conversation {conversationId}</p> : null}
        {error ? (
          <div className="error-row" role="alert">
            <span>We could not send that message.</span>
            {lastFailedContent ? (
              <button type="button" className="link-button" onClick={() => void submitContent(lastFailedContent)}>
                Retry
              </button>
            ) : null}
          </div>
        ) : null}

        <form ref={formRef} className="composer" onSubmit={submit}>
          <label htmlFor="message">Message</label>
          <textarea
            id="message"
            name="message"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            maxLength={8000}
            placeholder="How can we help?"
            rows={3}
            disabled={pending}
          />
          <div className="composer-footer">
            <span className="hint">Enter to send · Shift+Enter for a new line</span>
            <button className="send-button" type="submit" disabled={pending || !draft.trim()}>
              {pending ? "Sending…" : "Send"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
