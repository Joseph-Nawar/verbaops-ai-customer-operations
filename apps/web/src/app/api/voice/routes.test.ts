import { describe, expect, it, vi } from "vitest";

import { POST as createVoiceSession } from "./sessions/route";
import { POST as endVoiceSession } from "./sessions/[voiceSessionId]/end/route";
import { forwardToVerbaOps } from "@/lib/server/verbaops";

vi.mock("@/lib/server/verbaops", () => ({
  forwardToVerbaOps: vi.fn(),
  validationError: (message = "The request is invalid.") =>
    Response.json({ error: { code: "request_validation_error", message } }, { status: 422 }),
}));

const forwardMock = vi.mocked(forwardToVerbaOps);
const voiceSessionId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const conversationId = "55fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const bootstrap = {
  voice_session_id: voiceSessionId,
  conversation_id: conversationId,
  livekit_url: "wss://livekit.example.test",
  room_token: "transient-test-token",
  token_expires_at: "2026-10-08T12:00:00.000Z",
  status: "created",
};

describe("voice session BFF routes", () => {
  it("accepts an empty start body and returns exactly the approved bootstrap fields", async () => {
    forwardMock.mockResolvedValueOnce(Response.json(bootstrap, { status: 201 }));

    const response = await createVoiceSession(
      new Request("http://web.test/api/voice/sessions", {
        method: "POST",
        body: JSON.stringify({}),
      }),
    );

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual(bootstrap);
    expect(forwardMock).toHaveBeenCalledWith("v1/voice/sessions", {
      method: "POST",
      body: JSON.stringify({}),
    });
  });

  it("forwards only an optional conversation identifier", async () => {
    forwardMock.mockResolvedValueOnce(Response.json(bootstrap, { status: 201 }));

    const response = await createVoiceSession(
      new Request("http://web.test/api/voice/sessions", {
        method: "POST",
        body: JSON.stringify({ conversation_id: conversationId }),
      }),
    );

    expect(response.status).toBe(201);
    expect(forwardMock).toHaveBeenCalledWith("v1/voice/sessions", {
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId }),
    });
  });

  it.each([
    { tenant_id: "tenant" },
    { principal_id: "principal" },
    { customer_id: "customer" },
    { roles: ["customer"] },
    { room_name: "server-room" },
    { participant_identity: "server-participant" },
    { access_token: "forged-token" },
    { grant: { room_join: true } },
  ])("rejects browser-controlled voice field %j", async (body) => {
    forwardMock.mockClear();

    const response = await createVoiceSession(
      new Request("http://web.test/api/voice/sessions", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    );

    expect(response.status).toBe(422);
    expect(forwardMock).not.toHaveBeenCalled();
  });

  it("rejects malformed successful bootstrap responses without echoing them", async () => {
    forwardMock.mockResolvedValueOnce(
      Response.json({ ...bootstrap, livekit_url: "https://livekit.example.test", secret: "must-not-echo" }, { status: 201 }),
    );

    const response = await createVoiceSession(
      new Request("http://web.test/api/voice/sessions", { method: "POST", body: JSON.stringify({}) }),
    );

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: { code: "backend_unavailable", message: "The service is temporarily unavailable." },
    });
    expect(response.headers.get("content-type")).toContain("application/json");
  });

  it.each([
    "http://livekit.example.test",
    "ftp://livekit.example.test",
    "wss://user:secret@livekit.example.test",
    "wss://livekit.example.test?token=secret",
    "wss://livekit.example.test#fragment",
  ])("rejects unsafe LiveKit URL %s from a successful upstream response", async (livekitUrl) => {
    forwardMock.mockResolvedValueOnce(Response.json({ ...bootstrap, livekit_url: livekitUrl }, { status: 201 }));

    const response = await createVoiceSession(
      new Request("http://web.test/api/voice/sessions", { method: "POST", body: JSON.stringify({}) }),
    );

    expect(response.status).toBe(503);
  });

  it("maps upstream failures to a safe response", async () => {
    forwardMock.mockResolvedValueOnce(
      Response.json({ error: { code: "not_authorized", message: "secret backend detail" } }, { status: 403 }),
    );

    const response = await createVoiceSession(
      new Request("http://web.test/api/voice/sessions", { method: "POST", body: JSON.stringify({}) }),
    );

    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("secret backend detail");
  });

  it("validates the end path and forwards no browser body", async () => {
    forwardMock.mockResolvedValueOnce(Response.json({ status: "ended" }, { status: 200 }));

    const response = await endVoiceSession(
      new Request(`http://web.test/api/voice/sessions/${voiceSessionId}/end`, {
        method: "POST",
        body: JSON.stringify({ customer_id: "forged" }),
      }),
      { params: Promise.resolve({ voiceSessionId }) },
    );

    expect(response.status).toBe(200);
    expect(forwardMock).toHaveBeenCalledWith(`v1/voice/sessions/${voiceSessionId}/end`, { method: "POST" });
  });

  it("rejects an invalid end path without contacting the backend", async () => {
    forwardMock.mockClear();

    const response = await endVoiceSession(
      new Request("http://web.test/api/voice/sessions/not-a-uuid/end", { method: "POST" }),
      { params: Promise.resolve({ voiceSessionId: "not-a-uuid" }) },
    );

    expect(response.status).toBe(422);
    expect(forwardMock).not.toHaveBeenCalled();
  });
});
