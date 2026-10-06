import { forwardToVerbaOps, validationError } from "@/lib/server/verbaops";
import {
  encodedUuid,
  isProposalFingerprint,
  isRecord,
  isUuid,
  readJson,
} from "@/lib/server/request-validation";

export type ActionRequestRouteContext = {
  params: Promise<{ actionRequestId: string }>;
};

async function actionRequestId(context: ActionRequestRouteContext): Promise<string | null> {
  const { actionRequestId } = await context.params;
  return isUuid(actionRequestId) ? encodedUuid(actionRequestId) : null;
}

export async function forwardActionRequestGet(
  context: ActionRequestRouteContext,
): Promise<Response> {
  const encodedId = await actionRequestId(context);
  if (encodedId === null) return validationError();
  return forwardToVerbaOps(`v1/action-requests/${encodedId}`, { method: "GET" });
}

export async function forwardDecision(
  request: Request,
  context: ActionRequestRouteContext,
  operation: "confirmation" | "rejection" | "approval" | "approval-rejection",
): Promise<Response> {
  const encodedId = await actionRequestId(context);
  const body = await readJson(request);
  if (
    encodedId === null ||
    !isRecord(body) ||
    Object.keys(body).length !== 1 ||
    !isProposalFingerprint(body.proposal_fingerprint)
  ) {
    return validationError();
  }
  return forwardToVerbaOps(`v1/action-requests/${encodedId}/${operation}`, {
    method: "POST",
    body: JSON.stringify({ proposal_fingerprint: body.proposal_fingerprint }),
  });
}

export async function forwardReconciliation(
  request: Request,
  context: ActionRequestRouteContext,
): Promise<Response> {
  const encodedId = await actionRequestId(context);
  if (encodedId === null || request.body !== null) return validationError();
  return forwardToVerbaOps(`v1/action-requests/${encodedId}/reconciliation`, {
    method: "POST",
  });
}
