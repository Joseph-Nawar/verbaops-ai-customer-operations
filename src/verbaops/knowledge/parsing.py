"""Deterministic Markdown normalization and section detection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Section:
    """One Markdown ATX section and its normalized body."""

    title: str
    level: int
    content: str


_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$")


def normalize_markdown(source: bytes | str) -> str:
    """Decode and canonicalize a Markdown document without changing its meaning."""

    value = source.decode("utf-8", errors="strict") if isinstance(source, bytes) else source
    value = unicodedata.normalize("NFC", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in value.split("\n")]
    normalized: list[str] = []
    blank_count = 0
    for line in lines:
        if line:
            blank_count = 0
            normalized.append(line)
        elif blank_count < 1:
            blank_count += 1
            normalized.append("")
    while normalized and normalized[-1] == "":
        normalized.pop()
    return "\n".join(normalized) + ("\n" if normalized else "")


def detect_sections(markdown: str) -> list[Section]:
    """Split normalized Markdown at ATX headings, retaining an Introduction."""

    lines = markdown.splitlines()
    sections: list[Section] = []
    current_title = "Introduction"
    current_level = 0
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content or not sections:
            sections.append(Section(current_title, current_level, content))

    for line in lines:
        match = _HEADING.match(line)
        if match is None:
            current_lines.append(line)
            continue
        flush()
        current_title = match.group(2).rstrip("#").rstrip()
        current_level = len(match.group(1))
        current_lines = []
    if current_lines:
        flush()
    return [section for section in sections if section.content]
