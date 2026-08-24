import { forwardToVerbaOps, validationError } from "@/lib/server/verbaops";
import { encodedConversationId, isConversationId } from "@/lib/server/request-validation";

type RouteContext = { params: Promise<{ conversationId: string }> };

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  const { conversationId } = await context.params;
  if (!isConversationId(conversationId)) return validationError();
  const incoming = new URL(request.url).searchParams;
  const outgoing = new URLSearchParams();
  for (const name of ["limit", "before_sequence"]) {
    const value = incoming.get(name);
    if (value !== null) outgoing.set(name, value);
  }
  const limit = outgoing.get("limit");
  const before = outgoing.get("before_sequence");
  if (limit !== null && (!/^\d+$/.test(limit) || Number(limit) < 1 || Number(limit) > 100)) {
    return validationError();
  }
  if (before !== null && (!/^\d+$/.test(before) || Number(before) < 1)) return validationError();
  const suffix = outgoing.toString() ? `?${outgoing.toString()}` : "";
  return forwardToVerbaOps(`v1/conversations/${encodedConversationId(conversationId)}${suffix}`, {
    method: "GET",
  });
}
