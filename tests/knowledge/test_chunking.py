from verbaops.knowledge.chunking import chunk_sections, content_hash, source_hash
from verbaops.knowledge.parsing import detect_sections


def test_chunks_are_deterministic_indexed_and_section_local() -> None:
    source = "# First\n" + " ".join(f"first{i}" for i in range(220)) + "\n# Second\nsecond text"
    sections = detect_sections(source)

    first = chunk_sections(sections)
    second = chunk_sections(sections)

    assert first == second
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert all(chunk.section in {"First", "Second"} for chunk in first)
    assert all(len(chunk.content.split()) <= 180 for chunk in first)
    assert first[-1].section == "Second"


def test_long_section_chunks_overlap_by_thirty_tokens() -> None:
    sections = detect_sections("# Policy\n" + " ".join(f"word{i}" for i in range(300)))

    chunks = chunk_sections(sections)

    assert len(chunks) == 2
    assert chunks[0].content.split()[-30:] == chunks[1].content.split()[:30]


def test_hashes_are_sha256_over_canonical_content() -> None:
    assert source_hash("hello\n") == source_hash("hello\n")
    assert len(source_hash("hello\n")) == 64
    assert (
        content_hash("hello\n")
        == "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    )
