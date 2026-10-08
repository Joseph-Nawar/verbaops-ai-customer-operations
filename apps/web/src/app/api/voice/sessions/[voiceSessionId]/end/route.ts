import { isUuid } from "@/lib/server/request-validation";
import { forwardToVerbaOps, validationError } from "@/lib/server/verbaops";

type RouteContext = { params: Promise<{ voiceSessionId: string }> };

function safeBackendFailure(): Response {
  return Response.json(
    { error: { code: "backend_unavailable", message: "The service is temporarily unavailable." } },
    { status: 503 },
  );
}

export async function POST(_request: Request, context: RouteContext): Promise<Response> {
  const { voiceSessionId } = await context.params;
  if (!isUuid(voiceSessionId)) return validationError();

  const upstream = await forwardToVerbaOps(`v1/voice/sessions/${encodeURIComponent(voiceSessionId)}/end`, {
    method: "POST",
  });
  if (!upstream.ok) return safeBackendFailure();
  return upstream;
}
