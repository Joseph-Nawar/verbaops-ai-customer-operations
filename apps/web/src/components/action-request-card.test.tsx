import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ActionRequestCard, type ActionRequestView } from "./action-request-card";

const fingerprint = "a".repeat(64);

const proposalCases: Array<
  [ActionRequestView["action_type"], NonNullable<ActionRequestView["proposal"]>, string[]]
> = [
  [
    "reschedule_delivery",
    { action_type: "reschedule_delivery", order_id: "order-1", delivery_slot_id: "slot-1" },
    ["Order order-1", "Requested delivery slot slot-1", "changes delivery scheduling"],
  ],
  [
    "cancel_order",
    { action_type: "cancel_order", order_id: "order-1" },
    ["Order order-1", "Cancellation is not itself a refund"],
  ],
  [
    "initiate_return",
    {
      action_type: "initiate_return",
      order_id: "order-1",
      items: [{ order_item_id: "item-1", quantity: 2 }],
      reason: "Damaged",
    },
    ["Order order-1", "item-1", "Quantity: 2", "Damaged", "does not guarantee a refund"],
  ],
  [
    "create_support_ticket",
    {
      action_type: "create_support_ticket",
      order_id: "order-1",
      category: "delivery",
      subject: "Late delivery",
      description: "The delivery is late.",
    },
    ["Category: delivery", "Late delivery", "The delivery is late.", "Order order-1"],
  ],
  [
    "request_refund",
    { action_type: "request_refund", order_id: "order-1", amount: "45.00", reason: "Damaged" },
    ["45.00 USD", "Order order-1", "Damaged", "not payment settlement"],
  ],
];

function view(overrides: Partial<ActionRequestView> = {}): ActionRequestView {
  return {
    action_request_id: "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
    action_type: "cancel_order",
    state: "awaiting_confirmation",
    proposal_fingerprint: fingerprint,
    proposal: {
      action_type: "cancel_order",
      order_id: "11111111-1111-1111-8111-111111111111",
    },
    safe_summary: "Cancel order request",
    currency_code: null,
    required_next_actor: "customer",
    expires_at: "2026-10-06T12:00:00Z",
    customer_decision: null,
    result_status: null,
    confirmation_required: true,
    approval_required: false,
    policy_reason_code: "allowed",
    permitted_operations: ["confirm", "reject"],
    ...overrides,
  };
}

describe("ActionRequestCard", () => {
  it.each(proposalCases)("renders exact stored %s proposal material", (_actionType, proposal, expected) => {
    render(
        <ActionRequestCard
        actionRequest={view({
          action_type: _actionType as ActionRequestView["action_type"],
          proposal,
          currency_code: _actionType === "request_refund" ? "USD" : null,
        })}
      />,
    );
    for (const text of expected) expect(screen.getByText(new RegExp(text, "i"))).toBeInTheDocument();
  });

  it("renders customer controls only from permitted operations and submits ID/fingerprint", async () => {
    const user = userEvent.setup();
    const onUpdated = vi.fn();
    const updated = view({ state: "ready_to_execute", permitted_operations: [] });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(updated), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ActionRequestCard actionRequest={view()} onUpdated={onUpdated} />);
    await user.click(screen.getByRole("button", { name: "Confirm request" }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/action-requests/45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2/confirmation",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ proposal_fingerprint: fingerprint }),
      }),
    );
    expect(onUpdated).toHaveBeenCalledWith(updated);
  });

  it("reloads authoritative state after a decision conflict", async () => {
    const user = userEvent.setup();
    const onUpdated = vi.fn();
    const refreshed = view({ state: "expired", permitted_operations: [] });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "conflict" } }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(refreshed), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ActionRequestCard actionRequest={view()} onUpdated={onUpdated} />);
    await user.click(screen.getByRole("button", { name: "Confirm request" }));

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/action-requests/45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2",
      expect.objectContaining({ method: "GET" }),
    );
    expect(onUpdated).toHaveBeenCalledWith(refreshed);
  });

  it("does not show customer approval or supervisor controls from lifecycle state alone", () => {
    render(
      <ActionRequestCard
        actionRequest={view({
          state: "awaiting_approval",
          required_next_actor: "support_supervisor",
          permitted_operations: ["reject"],
        })}
      />,
    );
    expect(screen.getByText("Waiting for supervisor approval.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Withdraw request" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve request" })).not.toBeInTheDocument();
  });

  it("shows supervisor approval only when server permits it and suppresses proposer self-approval", () => {
    const { rerender } = render(
      <ActionRequestCard
        actionRequest={view({
          state: "awaiting_approval",
          permitted_operations: ["approve", "approval_reject"],
        })}
      />,
    );
    expect(screen.getByRole("button", { name: "Approve request" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject approval" })).toBeInTheDocument();

    rerender(
      <ActionRequestCard
        actionRequest={view({
          state: "awaiting_approval",
          permitted_operations: ["reject"],
        })}
      />,
    );
    expect(screen.queryByRole("button", { name: "Approve request" })).not.toBeInTheDocument();
  });

  it("does not describe unresolved as failed or succeeded and gates success on verification", () => {
    const { rerender } = render(
      <ActionRequestCard
        actionRequest={view({ state: "unresolved", permitted_operations: ["reconcile"] })}
      />,
    );
    expect(screen.getByText("The result could not be verified yet.")).toBeInTheDocument();
    expect(screen.queryByText(/failed|succeeded|completed/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconcile request" })).toBeInTheDocument();

    rerender(<ActionRequestCard actionRequest={view({ state: "succeeded", result_status: "verified" })} />);
    expect(screen.getByText(/verified/i)).toBeInTheDocument();
  });
});
