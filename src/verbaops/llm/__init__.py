"""Application-owned models for the VerbaOps LLM gateway."""

from verbaops.llm.client import LLMClient
from verbaops.llm.errors import (
    LLMAuthenticationError,
    LLMError,
    LLMProtocolError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from verbaops.llm.litellm import LiteLLMClient
from verbaops.llm.models import (
    CapabilityAlias,
    ChatMessage,
    GenerateRequest,
    GenerateResponse,
    ResponseMetadata,
    StructuredResponse,
    ToolCall,
    ToolDefinition,
)

__all__ = [
    "CapabilityAlias",
    "ChatMessage",
    "GenerateRequest",
    "GenerateResponse",
    "LLMAuthenticationError",
    "LLMClient",
    "LLMError",
    "LLMProtocolError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "LiteLLMClient",
    "ResponseMetadata",
    "StructuredResponse",
    "ToolCall",
    "ToolDefinition",
]
