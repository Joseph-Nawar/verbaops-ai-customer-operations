import http from "node:http";

const token = process.env.SMOKE_BACKEND_TOKEN ?? "smoke-backend-token";
const conversationId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const orderId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const proposalActionId = "11111111-1111-5111-8111-111111111111";
const approvalActionId = "22222222-2222-5222-8222-222222222222";
const unresolvedActionId = "33333333-3333-5333-8333-333333333333";
const succeededActionId = "44444444-4444-5444-8444-444444444444";
const proposalFingerprint = "a".repeat(64);
let conversationCreates = 0;
let messages = [];
let proposalCreated = false;
let proposalState = "awaiting_confirmation";
let supervisorMode = false;
const confirmationBodies = [];

function send(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

function authorized(request) {
  return request.headers.authorization === `Bearer ${token}`;
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  if (url.pathname === "/health") return send(response, 200, { ok: true });
  if (url.pathname === "/__state") {
    return send(response, 200, { conversationCreates, messages, confirmationBodies });
  }
  if (request.method === "POST" && url.pathname === "/__mode/supervisor") {
    supervisorMode = true;
    return send(response, 204, null);
  }
  if (!authorized(request)) return send(response, 401, { error: { code: "authentication_failed" } });

  function actionView(actionRequestId) {
    if (actionRequestId === proposalActionId) {
      return {
        action_request_id: proposalActionId,
        action_type: "cancel_order",
        state: proposalState,
        proposal_fingerprint: proposalFingerprint,
        proposal: { action_type: "cancel_order", order_id: orderId },
        safe_summary: "Cancel order request",
        currency_code: null,
        required_next_actor: proposalState === "succeeded" ? "none" : "customer",
        expires_at: "2026-10-06T12:00:00Z",
        customer_decision: proposalState === "succeeded" ? "confirmed" : null,
        result_status: proposalState === "succeeded" ? "verified" : null,
        confirmation_required: true,
        approval_required: false,
        policy_reason_code: "allowed",
        permitted_operations: proposalState === "awaiting_confirmation" ? ["confirm", "reject"] : [],
      };
    }
    if (actionRequestId === approvalActionId) {
      return {
        action_request_id: approvalActionId,
        action_type: "request_refund",
        state: "awaiting_approval",
        proposal_fingerprint: proposalFingerprint,
        proposal: { action_type: "request_refund", order_id: orderId, amount: "45.00", reason: "Damaged" },
        safe_summary: "Refund request awaiting approval",
        currency_code: "USD",
        required_next_actor: "support_supervisor",
        expires_at: "2026-10-06T12:00:00Z",
        customer_decision: null,
        result_status: null,
        confirmation_required: true,
        approval_required: true,
        policy_reason_code: "approval_required",
        permitted_operations: supervisorMode ? ["approve", "approval_reject"] : ["reject"],
      };
    }
    if (actionRequestId === unresolvedActionId) {
      return {
        action_request_id: unresolvedActionId,
        action_type: "cancel_order",
        state: "unresolved",
        proposal_fingerprint: proposalFingerprint,
        proposal: { action_type: "cancel_order", order_id: orderId },
        safe_summary: "Cancellation result could not be verified",
        currency_code: null,
        required_next_actor: "customer",
        expires_at: "2026-10-06T12:00:00Z",
        customer_decision: "confirmed",
        result_status: "unavailable",
        confirmation_required: true,
        approval_required: false,
        policy_reason_code: "allowed",
        permitted_operations: ["reconcile"],
      };
    }
    if (actionRequestId === succeededActionId) {
      return {
        action_request_id: succeededActionId,
        action_type: "cancel_order",
        state: "succeeded",
        proposal_fingerprint: proposalFingerprint,
        proposal: { action_type: "cancel_order", order_id: orderId },
        safe_summary: "Cancellation verified",
        currency_code: null,
        required_next_actor: "none",
        expires_at: "2026-10-06T12:00:00Z",
        customer_decision: "confirmed",
        result_status: "verified",
        confirmation_required: true,
        approval_required: false,
        policy_reason_code: "allowed",
        permitted_operations: [],
      };
    }
    return null;
  }

  if (request.method === "POST" && url.pathname === "/v1/conversations") {
    conversationCreates += 1;
    return send(response, 201, { conversation_id: conversationId });
  }
  if (request.method === "POST" && url.pathname === `/v1/conversations/${conversationId}/messages`) {
    let body = "";
    for await (const chunk of request) body += chunk;
    const content = JSON.parse(body).content;
    const proposal = content === "Create cancellation request";
    if (proposal) proposalCreated = true;
    const assistant = content === "Where is my order?"
      ? "Please provide your order ID."
      : proposal
        ? "I created a cancellation request for your review."
        : `Your order ${orderId} is in transit with Acme and tracking number T-1.`;
    const userMessage = { id: `user-${messages.length + 1}`, role: "user", content };
    const assistantMessage = { id: `assistant-${messages.length + 1}`, role: "assistant", content: assistant };
    messages.push(userMessage, assistantMessage);
    return send(response, 200, {
      conversation_id: conversationId,
      run_id: `run-${messages.length}`,
      user_message: userMessage,
      assistant_message: assistantMessage,
      action_requests: proposal ? [{ action_request_id: proposalActionId }] : [],
    });
  }
  if (request.method === "GET" && url.pathname.startsWith("/v1/action-requests/")) {
    const actionRequestId = url.pathname.split("/").at(-1);
    const action = actionView(actionRequestId);
    return action ? send(response, 200, action) : send(response, 404, { error: { code: "not_found" } });
  }
  if (request.method === "POST" && url.pathname === `/v1/action-requests/${proposalActionId}/confirmation`) {
    let body = "";
    for await (const chunk of request) body += chunk;
    confirmationBodies.push(JSON.parse(body));
    proposalState = "succeeded";
    return send(response, 200, actionView(proposalActionId));
  }
  if (request.method === "GET" && url.pathname === `/v1/conversations/${conversationId}`) {
    return send(response, 200, {
      conversation_id: conversationId,
      created_at: "2026-08-24T00:00:00Z",
      updated_at: "2026-08-24T00:00:00Z",
      messages,
      active_action_requests: proposalCreated && proposalState !== "succeeded" ? [actionView(proposalActionId)] : [],
      has_more: false,
      next_before_sequence: null,
    });
  }
  return send(response, 404, { error: { code: "not_found" } });
});

server.listen(Number(process.env.PORT ?? 4100), "127.0.0.1");
