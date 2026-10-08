import { isUuid } from "./server/request-validation";

export type VoiceSessionBootstrap = {
  voice_session_id: string;
  conversation_id: string;
  livekit_url: string;
  room_token: string;
  token_expires_at: string;
  status: "created";
};

const bootstrapKeys = [
  "conversation_id",
  "livekit_url",
  "room_token",
  "status",
  "token_expires_at",
  "voice_session_id",
].sort();

function hasExactKeys(value: Record<string, unknown>): boolean {
  return Object.keys(value).sort().join("\u0000") === bootstrapKeys.join("\u0000");
}

function isWebSocketUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      (url.protocol === "ws:" || url.protocol === "wss:") &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash
    );
  } catch {
    return false;
  }
}

export function isVoiceSessionBootstrap(value: unknown): value is VoiceSessionBootstrap {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    hasExactKeys(record) &&
    typeof record.voice_session_id === "string" &&
    isUuid(record.voice_session_id) &&
    typeof record.conversation_id === "string" &&
    isUuid(record.conversation_id) &&
    typeof record.livekit_url === "string" &&
    isWebSocketUrl(record.livekit_url) &&
    typeof record.room_token === "string" &&
    record.room_token.length > 0 &&
    typeof record.token_expires_at === "string" &&
    !Number.isNaN(Date.parse(record.token_expires_at)) &&
    record.status === "created"
  );
}

