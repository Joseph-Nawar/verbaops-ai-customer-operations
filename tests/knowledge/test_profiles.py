from verbaops.knowledge.profiles import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_PROFILE,
    format_passage,
    format_query,
)


def test_multilingual_e5_profile_formats_queries_and_passages_once() -> None:
    assert EMBEDDING_PROFILE == "multilingual-e5-base-v1"
    assert EMBEDDING_MODEL == "intfloat/multilingual-e5-base"
    assert EMBEDDING_DIMENSION == 768
    assert format_query("  return window? ") == "query: return window?"
    assert format_passage("Return window: 30 days.") == "passage: Return window: 30 days."

