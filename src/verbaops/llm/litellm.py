"""HTTP-only LiteLLM gateway adapter using the OpenAI chat-completions API."""

import json
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from verbaops.config.settings import LLMSettings
from verbaops.llm.client import LLMClient
from verbaops.llm.errors import (
    LLMAuthenticationError,
    LLMProtocolError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from verbaops.llm.models import (
    CapabilityAlias,
    GenerateRequest,
    GenerateResponse,
    ResponseMetadata,
    StructuredResponse,
    ToolCall,
)


class LiteLLMClient(LLMClient):
    """Normalize an OpenAI-compatible LiteLLM proxy behind VerbaOps models."""

    def __init__(
        self,
        settings: LLMSettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._endpoint = f"{settings.base_url.rstrip('/')}/chat/completions"

    def __repr__(self) -> str:
        """Avoid rendering settings, URLs, headers, or credentials."""

        return f"{type(self).__name__}(...)"

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Send a request to LiteLLM and normalize its OpenAI-compatible result."""

        payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        response, latency_ms = await self._post(payload)
        return self._parse_response(response, latency_ms, request.capability)

    async def generate_structured[T: BaseModel](
        self,
        request: GenerateRequest,
        response_model: type[T],
    ) -> StructuredResponse[T]:
        """Ask LiteLLM for strict JSON and validate it with the caller's model."""

        structured_request = request.model_copy(
            update={"response_format": StructuredResponse.response_format(response_model)}
        )
        response = await self.generate(structured_request)
        if response.content is None:
            raise LLMProtocolError()
        try:
            raw_data = json.loads(response.content)
        except (TypeError, ValueError):
            raise LLMProtocolError() from None
        if not isinstance(raw_data, dict):
            raise LLMProtocolError()
        try:
            data = response_model.model_validate(raw_data)
        except ValidationError:
            raise LLMProtocolError() from None
        return StructuredResponse(
            data=data,
            metadata=response.metadata,
            tool_calls=response.tool_calls,
        )

    async def _post(self, payload: dict[str, Any]) -> tuple[httpx.Response, float]:
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._settings.timeout_seconds,
            ) as client:
                response = await client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._settings.api_key.get_secret_value()}"
                    },
                    json=payload,
                )
        except httpx.TimeoutException:
            raise LLMTimeoutError() from None
        except httpx.TransportError:
            raise LLMUnavailableError() from None

        latency_ms = (perf_counter() - started_at) * 1000
        if response.status_code in (401, 403):
            raise LLMAuthenticationError()
        if response.status_code == 429:
            raise LLMRateLimitError()
        if response.status_code >= 500:
            raise LLMUnavailableError()
        if response.status_code >= 400:
            raise LLMProtocolError()
        return response, latency_ms

    def _parse_response(
        self,
        response: httpx.Response,
        latency_ms: float,
        capability_alias: CapabilityAlias,
    ) -> GenerateResponse:
        try:
            payload = response.json()
        except (UnicodeDecodeError, ValueError):
            raise LLMProtocolError() from None
        if not isinstance(payload, dict):
            raise LLMProtocolError()

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LLMProtocolError()
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise LLMProtocolError()

        content = self._optional_string(message.get("content"))
        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        request_id = response.headers.get("x-request-id")
        if request_id is None:
            request_id = self._optional_string(payload.get("id"))
        metadata = ResponseMetadata(
            capability_alias=capability_alias,
            request_id=request_id,
            model=self._optional_string(payload.get("model")),
            provider=self._provider(payload),
            input_tokens=self._usage_value(payload, "prompt_tokens"),
            output_tokens=self._usage_value(payload, "completion_tokens"),
            total_tokens=self._usage_value(payload, "total_tokens"),
            latency_ms=latency_ms,
            cost=self._cost(payload),
            finish_reason=self._optional_string(choice.get("finish_reason")),
        )
        return GenerateResponse(content=content, metadata=metadata, tool_calls=tool_calls)

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        raise LLMProtocolError()

    def _parse_tool_calls(self, value: object) -> tuple[ToolCall, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise LLMProtocolError()

        tool_calls: list[ToolCall] = []
        for item in value:
            if not isinstance(item, dict):
                raise LLMProtocolError()
            function = item.get("function")
            if not isinstance(function, dict):
                raise LLMProtocolError()
            call_id = self._optional_string(item.get("id"))
            name = self._optional_string(function.get("name"))
            arguments = function.get("arguments")
            if call_id is None or name is None or not isinstance(arguments, str):
                raise LLMProtocolError()
            try:
                parsed_arguments = json.loads(arguments)
            except (TypeError, ValueError):
                raise LLMProtocolError() from None
            if not isinstance(parsed_arguments, dict):
                raise LLMProtocolError()
            tool_calls.append(ToolCall(id=call_id, name=name, arguments=parsed_arguments))
        return tuple(tool_calls)

    def _usage_value(self, payload: dict[str, Any], name: str) -> int | None:
        usage = payload.get("usage")
        if usage is None:
            return None
        if not isinstance(usage, dict):
            raise LLMProtocolError()
        value = usage.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise LLMProtocolError()
        return int(value)

    def _provider(self, payload: dict[str, Any]) -> str | None:
        if "provider" in payload:
            return self._optional_string(payload["provider"])
        if "litellm_provider" in payload:
            return self._optional_string(payload["litellm_provider"])
        return None

    def _cost(self, payload: dict[str, Any]) -> float | None:
        if "response_cost" in payload:
            value = payload["response_cost"]
        elif "cost" in payload:
            value = payload["cost"]
        else:
            return None
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise LLMProtocolError()
        return float(value)
