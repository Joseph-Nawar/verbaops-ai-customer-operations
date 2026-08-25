"""Tests for strict JSONL case loading."""

from pathlib import Path

import pytest

from verbaops.evaluation.cases import CorpusFormatError, load_cases


def test_load_cases_reads_ordered_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"case_id":"x","dataset_version":"text-agent-v0.1","split":"dev",'
        '"language":"en","category":"benign-no-tool","customer_id":null,'
        '"conversation":[{"role":"user","content":"Hello"}],"expected_tool":null,'
        '"expected_arguments":{},"expected_outcome":{"kind":"benign_response"},'
        '"requires_confirmation":false,"forbidden_actions":[]}'
        "\n",
        encoding="utf-8",
    )
    cases = load_cases(path)
    assert [case.case_id for case in cases] == ["x"]


def test_load_cases_reports_line_number_for_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(CorpusFormatError, match="line 1"):
        load_cases(path)


def test_load_cases_rejects_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(CorpusFormatError, match="line 1"):
        load_cases(path)
