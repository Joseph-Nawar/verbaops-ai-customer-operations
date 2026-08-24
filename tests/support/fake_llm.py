"""Scripted LLM client for deterministic graph tests."""

from collections.abc import Iterable

from verbaops.llm.client import LLMClient
from verbaops.llm.models import GenerateRequest, GenerateResponse, StructuredResponse


class ScriptedLLMClient(LLMClient):
    """Return a fixed sequence of application-owned responses and record requests."""

    def __init__(self, responses: Iterable[GenerateResponse]) -> None:
        self.requests: list[GenerateRequest] = []
        self._responses = list(responses)

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("scripted LLM response queue is empty")
        return self._responses.pop(0)

    async def generate_structured[T](
        self,
        request: GenerateRequest,
        response_model: type[T],
    ) -> StructuredResponse[T]:
        del request, response_model
        raise AssertionError("structured generation is not used by the text agent")
