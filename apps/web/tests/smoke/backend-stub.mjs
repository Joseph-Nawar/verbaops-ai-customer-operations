import http from "node:http";

const token = process.env.SMOKE_BACKEND_TOKEN ?? "smoke-backend-token";
const conversationId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const orderId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
let conversationCreates = 0;
let messages = [];

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
    return send(response, 200, { conversationCreates, messages });
  }
  if (!authorized(request)) return send(response, 401, { error: { code: "authentication_failed" } });

  if (request.method === "POST" && url.pathname === "/v1/conversations") {
    conversationCreates += 1;
    return send(response, 201, { conversation_id: conversationId });
  }
  if (request.method === "POST" && url.pathname === `/v1/conversations/${conversationId}/messages`) {
    let body = "";
    for await (const chunk of request) body += chunk;
    const content = JSON.parse(body).content;
    const assistant = content === "Where is my order?"
      ? "Please provide your order ID."
      : `Your order ${orderId} is in transit with Acme and tracking number T-1.`;
    const userMessage = { id: `user-${messages.length + 1}`, role: "user", content };
    const assistantMessage = { id: `assistant-${messages.length + 1}`, role: "assistant", content: assistant };
    messages.push(userMessage, assistantMessage);
    return send(response, 200, {
      conversation_id: conversationId,
      run_id: `run-${messages.length}`,
      user_message: userMessage,
      assistant_message: assistantMessage,
    });
  }
  if (request.method === "GET" && url.pathname === `/v1/conversations/${conversationId}`) {
    return send(response, 200, {
      conversation_id: conversationId,
      created_at: "2026-08-24T00:00:00Z",
      updated_at: "2026-08-24T00:00:00Z",
      messages,
      has_more: false,
      next_before_sequence: null,
    });
  }
  return send(response, 404, { error: { code: "not_found" } });
});

server.listen(Number(process.env.PORT ?? 4100), "127.0.0.1");
