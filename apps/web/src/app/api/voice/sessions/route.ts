import { isVoiceSessionBootstrap } from "@/lib/voice-contract";
import { isRecord, isUuid, readJson } from "@/lib/server/request-validation";
import { forwardToVerbaOps, validationError } from "@/lib/server/verbaops";

function safeBackendFailure(): Response {
  return Response.json(
    { error: { code: "backend_unavailable", message: "The service is temporarily unavailable." } },
    { status: 503 },
  );
}

export async function POST(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isRecord(body)) return validationError();

  const keys = Object.keys(body);
  if (keys.some((key) => key !== "conversation_id")) return validationError();
  if ("conversation_id" in body && (typeof body.conversation_id !== "string" || !isUuid(body.conversation_id))) {
    return validationError();
  }

  const forwardedBody = "conversation_id" in body ? { conversation_id: body.conversation_id } : {};
  const upstream = await forwardToVerbaOps("v1/voice/sessions", {
    method: "POST",
    body: JSON.stringify(forwardedBody),
  });
  if (!upstream.ok) return safeBackendFailure();

  let responseBody: unknown;
  try {
    responseBody = await upstream.json();
  } catch {
    return safeBackendFailure();
  }
  if (!isVoiceSessionBootstrap(responseBody)) return safeBackendFailure();
  return Response.json(responseBody, { status: upstream.status });
}
