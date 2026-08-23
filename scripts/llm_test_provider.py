"""Deterministic local OpenAI-compatible provider for the LiteLLM contract."""

from __future__ import annotations

import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

API_KEY = os.environ.get("PROVIDER_TEST_API_KEY", "local-test-provider-key")


def _error(message: str, error_type: str, code: str) -> dict[str, Any]:
    return {"error": {"message": message, "type": error_type, "code": code}}


def _content_text(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""
    content = messages[-1].get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""


def _completion(request: dict[str, Any]) -> dict[str, Any]:
    marker = _content_text(request.get("messages", []))
    if "test:timeout" in marker:
        time.sleep(5)
    if "test:rate-limit" in marker:
        return _error("deterministic rate limit", "rate_limit_error", "rate_limit")
    if "test:server-error" in marker:
        return _error("deterministic provider failure", "server_error", "server_error")

    if "test:tool-call" in marker:
        tool = request.get("tools", [{}])[0]
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = function.get("name", "lookup_order")
        message: dict[str, Any] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_local_lookup",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(
                            {"order_id": "order-local-001", "action": "lookup"}
                        ),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
        completion_tokens = 9
    elif "test:structured" in marker:
        message = {
            "role": "assistant",
            "content": json.dumps({"answer": "deterministic", "score": 1.0}),
        }
        finish_reason = "stop"
        completion_tokens = 6
    else:
        message = {"role": "assistant", "content": "deterministic-stub-response"}
        finish_reason = "stop"
        completion_tokens = 4

    return {
        "id": "stub-chat-completion",
        "object": "chat.completion",
        "created": 1,
        "model": "local-test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 7,
            "completion_tokens": completion_tokens,
            "total_tokens": 7 + completion_tokens,
        },
    }


class ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: HTTPStatus, payload: object, *, raw: bytes | None = None) -> None:
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-request-id", "stub-request-id")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(HTTPStatus.OK, {"status": "ok"})
        elif self.path == "/v1/models":
            self._send(
                HTTPStatus.OK,
                {"object": "list", "data": [{"id": "local-test-model", "object": "model"}]},
            )
        else:
            self._send(
                HTTPStatus.NOT_FOUND, _error("not found", "invalid_request_error", "not_found")
            )

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send(
                HTTPStatus.NOT_FOUND, _error("not found", "invalid_request_error", "not_found")
            )
            return
        if self.headers.get("Authorization") != f"Bearer {API_KEY}":
            self._send(
                HTTPStatus.UNAUTHORIZED,
                _error("invalid local provider key", "authentication_error", "invalid_api_key"),
            )
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            request = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(
                HTTPStatus.BAD_REQUEST,
                _error("invalid JSON", "invalid_request_error", "invalid_json"),
            )
            return
        if "test:malformed" in _content_text(request.get("messages", [])):
            self._send(HTTPStatus.OK, {}, raw=b"{not-json")
            return
        payload = _completion(request)
        status = HTTPStatus.OK
        if payload.get("error", {}).get("code") == "rate_limit":
            status = HTTPStatus.TOO_MANY_REQUESTS
        elif payload.get("error", {}).get("code") == "server_error":
            status = HTTPStatus.SERVICE_UNAVAILABLE
        self._send(status, payload)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8000), ProviderHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
