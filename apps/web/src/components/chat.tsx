"use client";

import { FormEvent, KeyboardEvent, useRef, useState } from "react";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type MessageResponse = {
  conversation_id: string;
  user_message: Message;
  assistant_message: Message;
};

async function readApiResponse(response: Response): Promise<Record<string, unknown>> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok || typeof body !== "object" || body === null) throw new Error("request_failed");
  return body as Record<string, unknown>;
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
  return body as unknown as MessageResponse;
}

export function Chat(): React.JSX.Element {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const [lastFailedContent, setLastFailedContent] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  async function submitContent(content: string): Promise<void> {
    const cleanContent = content.trim();
    if (!cleanContent || pending) return;
    setPending(true);
    setError(false);
    setLastFailedContent(cleanContent);
    try {
      const id = conversationId ?? (await createConversation());
      if (!conversationId) setConversationId(id);
      const result = await sendMessage(id, cleanContent);
      setMessages((current) => [...current, result.user_message, result.assistant_message]);
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

  function reset(): void {
    setConversationId(null);
    setMessages([]);
    setDraft("");
    setError(false);
    setLastFailedContent(null);
  }

  return (
    <main className="chat-shell">
      <section className="chat-card" aria-labelledby="chat-title">
        <header className="chat-header">
          <div>
            <p className="eyebrow">NovaCommerce support</p>
            <h1 id="chat-title">VerbaOps AI</h1>
            <p className="subtitle">Read-only help for orders and deliveries.</p>
          </div>
          <button className="secondary-button" type="button" onClick={reset}>
            New conversation
          </button>
        </header>

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
