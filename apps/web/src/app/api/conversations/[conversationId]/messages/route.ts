import { forwardToVerbaOps, validationError } from "@/lib/server/verbaops";
import { encodedConversationId, isConversationId, isRecord, readJson } from "@/lib/server/request-validation";

type RouteContext = { params: Promise<{ conversationId: string }> };

export async function POST(request: Request, context: RouteContext): Promise<Response> {
  const { conversationId } = await context.params;
  const body = await readJson(request);
  if (!isConversationId(conversationId) || !isRecord(body)) return validationError();
  if (Object.keys(body).length !== 1 || typeof body.content !== "string") return validationError();
  const content = body.content.trim();
  if (content.length === 0 || content.length > 8000) return validationError();
  return forwardToVerbaOps(`v1/conversations/${encodedConversationId(conversationId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}
