"""Strict audit of the frozen RAG benchmark against the committed corpus."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from verbaops.evaluation.rag_models import RagCase, RagCorpusAudit
from verbaops.knowledge.chunking import MAX_CHUNK_TOKENS, OVERLAP_TOKENS, chunk_sections
from verbaops.knowledge.parsing import detect_sections, normalize_markdown


class RagCorpusError(ValueError):
    """Raised when a frozen RAG corpus violates a contract."""


EXPECTED_CATEGORIES = {
    "shipping": 15,
    "returns": 15,
    "refunds": 12,
    "warranty": 12,
    "payments": 10,
    "privacy": 8,
    "product-guides": 18,
    "faq": 15,
    "no-answer": 15,
}
EXPECTED_SPLITS = {"dev": 96, "release_holdout": 24}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rag_cases(path: Path) -> tuple[RagCase, ...]:
    cases: list[RagCase] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RagCorpusError(f"cannot read RAG dataset: {error}") from error
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            raise RagCorpusError(f"line {line_number}: blank lines are not allowed")
        try:
            cases.append(RagCase.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as error:
            raise RagCorpusError(f"line {line_number}: invalid RAG case: {error}") from error
    return tuple(cases)


def _normal_query(query: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", query).casefold().split())


def _known_locators(root: Path) -> set[tuple[str, str, str, int]]:
    manifest_path = root / "knowledge" / "novacommerce" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    locators: set[tuple[str, str, str, int]] = set()
    for entry in manifest["documents"]:
        source = root / "knowledge" / "novacommerce" / entry["path"]
        sections = detect_sections(normalize_markdown(source.read_bytes()))
        for chunk in chunk_sections(sections):
            locators.add((entry["slug"], entry["version"], chunk.section, chunk.chunk_index))
    return locators


def audit_rag_corpus(
    cases: tuple[RagCase, ...] | list[RagCase] | list[dict[str, Any]], root: Path
) -> RagCorpusAudit:
    """Validate shape, stable evidence references, and committed corpus resolution."""

    if cases and isinstance(cases[0], dict):
        try:
            typed_cases = tuple(RagCase.model_validate(case) for case in cases)
        except ValidationError as error:
            raise RagCorpusError(str(error)) from error
    else:
        typed_cases = tuple(cases)  # type: ignore[arg-type]
    errors: list[str] = []
    dataset_path = root / "evals" / "rag" / "v0.1" / "questions.jsonl"
    knowledge_path = root / "knowledge" / "novacommerce" / "manifest.json"
    benchmark_manifest_path = root / "evals" / "rag" / "v0.1" / "manifest.json"
    try:
        benchmark_manifest = json.loads(benchmark_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RagCorpusError(f"benchmark manifest could not be loaded: {error}") from error
    dataset_sha = sha256_file(dataset_path)
    knowledge_sha = sha256_file(knowledge_path)
    if benchmark_manifest.get("questions_sha256") != dataset_sha:
        errors.append("benchmark manifest questions SHA does not match dataset")
    if benchmark_manifest.get("knowledge_manifest_sha256") != knowledge_sha:
        errors.append("benchmark manifest knowledge SHA does not match corpus manifest")
    if benchmark_manifest.get("chunking") != {
        "max_chunk_tokens": MAX_CHUNK_TOKENS,
        "overlap_tokens": OVERLAP_TOKENS,
    }:
        errors.append("benchmark manifest chunking parameters do not match locked chunker")
    known = _known_locators(root)
    if len(typed_cases) != 120:
        errors.append(f"case count expected 120, got {len(typed_cases)}")
    split_counts: dict[str, int] = dict(Counter(case.split for case in typed_cases))
    if split_counts != EXPECTED_SPLITS:
        errors.append(f"split counts expected {EXPECTED_SPLITS}, got {split_counts}")
    category_counts: dict[str, int] = dict(Counter(case.category for case in typed_cases))
    if category_counts != EXPECTED_CATEGORIES:
        errors.append(f"category counts expected {EXPECTED_CATEGORIES}, got {category_counts}")
    ids = [case.case_id for case in typed_cases]
    if len(ids) != len(set(ids)):
        errors.append("duplicate case IDs")
    normalized_queries = [_normal_query(case.query) for case in typed_cases]
    if len(normalized_queries) != len(set(normalized_queries)):
        errors.append("duplicate normalized queries")
    for case in typed_cases:
        positive = 0
        judgment_keys: set[tuple[str, str, str, int]] = set()
        for judgment in case.relevance_judgments:
            if judgment.key() not in known:
                errors.append(
                    f"{case.case_id}: relevance locator does not resolve: {judgment.key()}"
                )
            judgment_keys.add(judgment.key())
            positive += int(judgment.relevance_grade > 0)
        if case.answerable and positive == 0:
            errors.append(f"{case.case_id}: answerable without positive relevance")
        if not case.answerable and positive:
            errors.append(f"{case.case_id}: no-answer has positive relevance")
        for fact in case.expected_facts:
            for locator in fact.supporting_locators:
                if locator.key() not in known or locator.key() not in judgment_keys:
                    errors.append(
                        f"{case.case_id}: fact support locator does not resolve: {locator.key()}"
                    )
        if case.dataset_version != "rag-v0.1" or case.language != "en":
            errors.append(f"{case.case_id}: dataset version/language mismatch")
    if errors:
        raise RagCorpusError("; ".join(errors))
    normalized_split_counts: dict[str, int] = {
        str(key): split_counts[key] for key in EXPECTED_SPLITS
    }
    normalized_category_counts: dict[str, int] = {
        str(key): category_counts[key] for key in EXPECTED_CATEGORIES
    }
    return RagCorpusAudit(
        dataset_version="rag-v0.1",
        language="en",
        case_count=len(typed_cases),
        split_counts=normalized_split_counts,
        category_counts=normalized_category_counts,
        dataset_sha256=dataset_sha,
        knowledge_manifest_sha256=knowledge_sha,
        chunk_count=len(known),
        chunking={"max_chunk_tokens": MAX_CHUNK_TOKENS, "overlap_tokens": OVERLAP_TOKENS},
    )
