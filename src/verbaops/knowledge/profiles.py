"""Versioned application-owned embedding profiles."""

EMBEDDING_PROFILE = "multilingual-e5-base-v1"
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
EMBEDDING_DIMENSION = 768


def _normalize_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("embedding text must not be blank")
    return normalized


def format_query(normalized_query: str) -> str:
    """Format a multilingual-e5 query exactly once at the application boundary."""

    return f"query: {_normalize_text(normalized_query)}"


def format_passage(chunk_content: str) -> str:
    """Format a multilingual-e5 passage exactly once at the application boundary."""

    return f"passage: {_normalize_text(chunk_content)}"


__all__ = [
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL",
    "EMBEDDING_PROFILE",
    "format_passage",
    "format_query",
]
