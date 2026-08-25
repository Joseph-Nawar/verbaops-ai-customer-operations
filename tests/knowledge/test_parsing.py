from verbaops.knowledge.parsing import detect_sections, normalize_markdown


def test_normalization_is_unicode_and_newline_deterministic() -> None:
    source = "# Café\r\n\r\n\r\nText  \rMore\n\n\n\n"

    assert normalize_markdown(source.encode("utf-8")) == "# Café\n\nText\nMore\n"


def test_content_before_first_heading_is_introduction() -> None:
    sections = detect_sections("Preamble\n\n# Shipping\nShips in two days.\n## Express\nNext day.")

    assert [(section.title, section.level, section.content) for section in sections] == [
        ("Introduction", 0, "Preamble"),
        ("Shipping", 1, "Ships in two days."),
        ("Express", 2, "Next day."),
    ]


def test_heading_detection_accepts_atx_levels_one_to_six() -> None:
    sections = detect_sections("# One\nA\n###### Six\nB")

    assert [section.title for section in sections] == ["One", "Six"]
    assert [section.level for section in sections] == [1, 6]
