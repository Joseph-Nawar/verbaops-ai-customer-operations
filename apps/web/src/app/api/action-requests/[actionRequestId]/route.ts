import {
  forwardActionRequestGet,
  type ActionRequestRouteContext,
} from "@/lib/server/action-request-routes";

export async function GET(_request: Request, context: ActionRequestRouteContext): Promise<Response> {
  return forwardActionRequestGet(context);
}
