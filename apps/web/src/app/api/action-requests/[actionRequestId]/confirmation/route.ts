import {
  forwardDecision,
  type ActionRequestRouteContext,
} from "@/lib/server/action-request-routes";

export async function POST(request: Request, context: ActionRequestRouteContext): Promise<Response> {
  return forwardDecision(request, context, "confirmation");
}
