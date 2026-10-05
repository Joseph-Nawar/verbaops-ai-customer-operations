"use client";

import { useState } from "react";

export type ActionType =
  | "reschedule_delivery"
  | "cancel_order"
  | "initiate_return"
  | "create_support_ticket"
  | "request_refund";
export type ActionState =
  | "proposed"
  | "policy_denied"
  | "awaiting_approval"
  | "awaiting_confirmation"
  | "ready_to_execute"
  | "executing"
  | "succeeded"
  | "rejected"
  | "failed"
  | "unresolved"
  | "expired";
export type ActionOperation = "confirm" | "reject" | "approve" | "approval_reject" | "reconcile";

type RescheduleProposal = {
  action_type: "reschedule_delivery";
  order_id: string;
  delivery_slot_id: string;
};
type CancelProposal = { action_type: "cancel_order"; order_id: string };
type ReturnProposal = {
  action_type: "initiate_return";
  order_id: string;
  items: Array<{ order_item_id: string; quantity: number }>;
  reason: string;
};
type TicketProposal = {
  action_type: "create_support_ticket";
  order_id: string | null;
  category: string;
  subject: string;
  description: string;
};
type RefundProposal = {
  action_type: "request_refund";
  order_id: string;
  amount: string;
  reason: string;
};

export type ActionProposal =
  | RescheduleProposal
  | CancelProposal
  | ReturnProposal
  | TicketProposal
  | RefundProposal;

export type ActionRequestView = {
  action_request_id: string;
  action_type: ActionType;
  state: ActionState;
  proposal_fingerprint: string;
  proposal: ActionProposal;
  safe_summary: string;
  currency_code: string | null;
  required_next_actor: "customer" | "support_supervisor" | "none";
  expires_at: string;
  customer_decision: "confirmed" | "rejected" | null;
  result_status: "verified" | "mismatched" | "unavailable" | null;
  confirmation_required: boolean;
  approval_required: boolean;
  policy_reason_code: string | null;
  permitted_operations: ActionOperation[];
};

type ActionRequestCardProps = {
  actionRequest: ActionRequestView;
  onUpdated?: (actionRequest: ActionRequestView) => void;
};

const operationPaths: Record<ActionOperation, string> = {
  confirm: "confirmation",
  reject: "rejection",
  approve: "approval",
  approval_reject: "approval-rejection",
  reconcile: "reconciliation",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isActionRequestView(value: unknown): value is ActionRequestView {
  if (!isRecord(value)) return false;
  return (
    typeof value.action_request_id === "string" &&
    typeof value.action_type === "string" &&
    typeof value.state === "string" &&
    typeof value.proposal_fingerprint === "string" &&
    /^[0-9a-f]{64}$/.test(value.proposal_fingerprint) &&
    isRecord(value.proposal) &&
    typeof value.safe_summary === "string" &&
    Array.isArray(value.permitted_operations) &&
    value.permitted_operations.every((operation) =>
      ["confirm", "reject", "approve", "approval_reject", "reconcile"].includes(String(operation)),
    )
  );
}

async function readActionView(response: Response): Promise<ActionRequestView> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok || !isActionRequestView(body)) throw new Error("request_failed");
  return body;
}

export async function loadActionView(actionRequestId: string): Promise<ActionRequestView> {
  return readActionView(
    await fetch(`/api/action-requests/${encodeURIComponent(actionRequestId)}`, {
      method: "GET",
      headers: { accept: "application/json" },
      cache: "no-store",
    }),
  );
}

function stateCopy(actionRequest: ActionRequestView): string {
  switch (actionRequest.state) {
    case "awaiting_approval":
      return "Waiting for supervisor approval.";
    case "awaiting_confirmation":
      return "Review and confirm this request.";
    case "ready_to_execute":
      return "Confirmed and queued for execution.";
    case "executing":
      return "The request is being processed.";
    case "succeeded":
      return actionRequest.result_status === "verified"
        ? "Verified business postcondition succeeded."
        : "The result is not verified.";
    case "failed":
      return "The request failed or was rejected.";
    case "unresolved":
      return "The result could not be verified yet.";
    case "expired":
      return "This request is stale or expired; create a new proposal.";
    case "rejected":
      return "This request was rejected.";
    case "policy_denied":
      return "This request was denied by policy.";
    default:
      return "This request is awaiting server processing.";
  }
}

function operationLabel(operation: ActionOperation): string {
  switch (operation) {
    case "confirm":
      return "Confirm request";
    case "reject":
      return "Withdraw request";
    case "approve":
      return "Approve request";
    case "approval_reject":
      return "Reject approval";
    case "reconcile":
      return "Reconcile request";
  }
}

function proposalDetails(proposal: ActionProposal, currencyCode: string | null): React.JSX.Element {
  switch (proposal.action_type) {
    case "reschedule_delivery":
      return (
        <>
          <p>Order {proposal.order_id}</p>
          <p>Requested delivery slot {proposal.delivery_slot_id}</p>
          <p>This changes delivery scheduling.</p>
        </>
      );
    case "cancel_order":
      return (
        <>
          <p>Order {proposal.order_id}</p>
          <p>Cancellation is not itself a refund.</p>
        </>
      );
    case "initiate_return":
      return (
        <>
          <p>Order {proposal.order_id}</p>
          {proposal.items.map((item) => (
            <p key={item.order_item_id}>
              Item {item.order_item_id}; Quantity: {item.quantity}
            </p>
          ))}
          <p>Reason: {proposal.reason}</p>
          <p>A return request does not guarantee a refund.</p>
        </>
      );
    case "create_support_ticket":
      return (
        <>
          <p>Category: {proposal.category}</p>
          <p>Subject: {proposal.subject}</p>
          <p>Description: {proposal.description}</p>
          {proposal.order_id ? <p>Order {proposal.order_id}</p> : null}
        </>
      );
    case "request_refund":
      return (
        <>
          <p>
            Refund amount: {proposal.amount} {currencyCode ?? "(currency unavailable)"}
          </p>
          <p>Order {proposal.order_id}</p>
          <p>Reason: {proposal.reason}</p>
          <p>Approval or request creation is not payment settlement.</p>
        </>
      );
  }
}

export function ActionRequestCard({ actionRequest, onUpdated }: ActionRequestCardProps): React.JSX.Element {
  const [pendingOperation, setPendingOperation] = useState<ActionOperation | null>(null);
  const [error, setError] = useState(false);

  async function submit(operation: ActionOperation): Promise<void> {
    if (pendingOperation !== null) return;
    setPendingOperation(operation);
    setError(false);
    try {
      const response = await fetch(
        `/api/action-requests/${encodeURIComponent(actionRequest.action_request_id)}/${operationPaths[operation]}`,
        {
          method: "POST",
          headers: { accept: "application/json", "content-type": "application/json" },
          body: operation === "reconcile" ? undefined : JSON.stringify({ proposal_fingerprint: actionRequest.proposal_fingerprint }),
          cache: "no-store",
        },
      );
      if (response.status === 409) {
        onUpdated?.(await loadActionView(actionRequest.action_request_id));
        return;
      }
      onUpdated?.(await readActionView(response));
    } catch {
      setError(true);
    } finally {
      setPendingOperation(null);
    }
  }

  return (
    <article className="action-card" aria-label={`${actionRequest.action_type} action request`}>
      <div className="action-card-header">
        <div>
          <p className="eyebrow">Action request</p>
          <h2>{actionRequest.action_type.replaceAll("_", " ")}</h2>
        </div>
        <span className="action-state">{actionRequest.state}</span>
      </div>
      <p className="action-state-copy">{stateCopy(actionRequest)}</p>
      <div className="action-details">{proposalDetails(actionRequest.proposal, actionRequest.currency_code)}</div>
      {error ? <p className="action-error" role="alert">The request could not be updated.</p> : null}
      {actionRequest.permitted_operations.length > 0 ? (
        <div className="action-controls">
          {actionRequest.permitted_operations.map((operation) => (
            <button
              className={operation === "confirm" || operation === "approve" ? "send-button" : "secondary-button"}
              disabled={pendingOperation !== null}
              key={operation}
              onClick={() => void submit(operation)}
              type="button"
            >
              {pendingOperation === operation ? "Updating…" : operationLabel(operation)}
            </button>
          ))}
        </div>
      ) : null}
    </article>
  );
}
