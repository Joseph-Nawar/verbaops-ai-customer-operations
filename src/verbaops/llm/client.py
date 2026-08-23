"""Application-owned interface for LLM gateway adapters."""

from abc import ABC, abstractmethod

from pydantic import BaseModel

from verbaops.llm.models import GenerateRequest, GenerateResponse, StructuredResponse


class LLMClient(ABC):
    """Generate plain and structured responses through an LLM gateway."""

    @abstractmethod
    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Generate a plain response for one OpenAI-compatible request."""

    @abstractmethod
    async def generate_structured[T: BaseModel](
        self,
        request: GenerateRequest,
        response_model: type[T],
    ) -> StructuredResponse[T]:
        """Generate and validate a structured response for one request."""
