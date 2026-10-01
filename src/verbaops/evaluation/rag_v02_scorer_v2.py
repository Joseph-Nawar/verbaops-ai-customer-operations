"""Small deterministic assertion recognizer for the M5D-B2 scorer contract.

This helper only recognizes benchmark-labeled fact units. It is not a general
claim verifier and does not judge whether arbitrary text is true.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class ScorerV2Error(ValueError):
    """Raised when the frozen scorer fixtures or provenance do not validate."""


class AssertionStatus(StrEnum):
    ASSERTED = "asserted"
    PARTIAL = "partial"
    NEGATED = "negated"
    CONTRADICTED = "contradicted"
    REFUSAL = "refusal"
    QUOTED = "quoted"
    UNCERTAIN = "uncertain"
    UNRELATED_OVERLAP = "unrelated_overlap"
    NOT_RECOGNIZED = "not_recognized"


@dataclass(frozen=True)
class FactAssertionAssessment:
    status: AssertionStatus
    recognized: bool
    matched_pattern: str | None = None


_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "with",
}
_REFUSAL_CUES = (
    "i cannot verify whether",
    "i cannot confirm whether",
    "i cannot confirm that",
    "i can not verify whether",
    "i can not confirm whether",
    "i do not have enough company information to say that",
    "i don t have enough company information to say that",
    "the available evidence does not confirm",
    "available evidence does not confirm",
    "the evidence does not confirm",
    "i cannot say whether",
    "i can not say whether",
)
_UNCERTAINTY_CUES = (
    "perhaps",
    "maybe",
    "possibly",
    "it may be that",
    "i am unsure whether",
    "i am not sure whether",
    "i m not sure whether",
)
_NEGATION_CUES = (
    "it is not true that",
    "it is not the case that",
    "the policy does not say that",
    "the evidence does not support that",
    "does not",
    "do not",
    "did not",
    "is not",
    "are not",
    "was not",
    "were not",
    "never",
    "no",
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;])\s+|[\r\n]+")
_QUOTED_SEGMENTS = (
    re.compile(r'"([^"\r\n]*)"'),
    re.compile(r"\u201c([^\r\n]*)\u201d"),
    re.compile(r"\u2018([^\r\n]*)\u2019"),
)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def _patterns(values: tuple[str, ...] | list[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize(value)
        if normalized and normalized not in seen:
            result.append((value, normalized))
            seen.add(normalized)
    return result


def _contains(normalized_text: str, normalized_phrase: str) -> bool:
    return f" {normalized_phrase} " in f" {normalized_text} "


def _quoted_matches(answer: str, patterns: list[tuple[str, str]]) -> bool:
    return any(
        _contains(_normalize(segment), pattern)
        for quote_pattern in _QUOTED_SEGMENTS
        for segment in quote_pattern.findall(answer)
        for _, pattern in patterns
    )


def _without_quoted_segments(answer: str) -> str:
    unquoted = answer
    for quote_pattern in _QUOTED_SEGMENTS:
        unquoted = quote_pattern.sub(" ", unquoted)
    return unquoted


def _prefix_status(sentence: str, phrase: str) -> AssertionStatus | None:
    normalized = _normalize(sentence)
    position = normalized.find(phrase)
    if position < 0:
        return None
    prefix = normalized[:position].split()
    nearby_prefix = " ".join(prefix[-16:])
    for cue in _REFUSAL_CUES:
        if _contains(nearby_prefix, _normalize(cue)):
            return AssertionStatus.REFUSAL
    for cue in _UNCERTAINTY_CUES:
        if _contains(nearby_prefix, _normalize(cue)):
            return AssertionStatus.UNCERTAIN
    for cue in _NEGATION_CUES:
        if _contains(nearby_prefix, _normalize(cue)):
            return AssertionStatus.NEGATED
    return None


def _content_terms(patterns: list[tuple[str, str]]) -> set[str]:
    return {token for _, phrase in patterns for token in phrase.split() if token not in _STOP_WORDS}


def _overlap_status(answer: str, positive_patterns: list[tuple[str, str]]) -> AssertionStatus:
    answer_terms = set(_normalize(answer).split())
    fact_terms = _content_terms(positive_patterns)
    overlap = answer_terms & fact_terms
    if not fact_terms or len(overlap) < 2 or len(overlap) / len(fact_terms) < 0.25:
        return AssertionStatus.NOT_RECOGNIZED

    normalized = _normalize(answer)
    if any(_contains(normalized, _normalize(cue)) for cue in _REFUSAL_CUES):
        return AssertionStatus.REFUSAL
    if any(_contains(normalized, _normalize(cue)) for cue in _UNCERTAINTY_CUES):
        return AssertionStatus.UNCERTAIN
    if any(_contains(normalized, _normalize(cue)) for cue in _NEGATION_CUES):
        return AssertionStatus.NEGATED
    return AssertionStatus.UNRELATED_OVERLAP


def classify_labeled_fact_assertion(
    answer: str,
    benchmark_aliases: tuple[str, ...] | list[str],
    *,
    positive_paraphrases: tuple[str, ...] | list[str] = (),
    partial_patterns: tuple[str, ...] | list[str] = (),
    contradiction_patterns: tuple[str, ...] | list[str] = (),
) -> FactAssertionAssessment:
    """Recognize only a direct, complete assertion of one labeled fact.

    Positive matching uses benchmark aliases and preregistered manual paraphrase
    phrases. Negated, uncertain, quoted, refusal, partial, and contradicted
    mentions are returned as non-recognized statuses. All other free text is
    left unrecognized; no arbitrary claim is judged for truth.
    """

    positive_patterns = _patterns([*benchmark_aliases, *positive_paraphrases])
    if not answer.strip() or not positive_patterns:
        return FactAssertionAssessment(AssertionStatus.NOT_RECOGNIZED, False)

    contradiction_patterns_normalized = _patterns(list(contradiction_patterns))
    normalized_answer = _normalize(answer)
    for original, pattern in contradiction_patterns_normalized:
        if _contains(normalized_answer, pattern):
            return FactAssertionAssessment(AssertionStatus.CONTRADICTED, False, original)

    quoted_match = _quoted_matches(answer, positive_patterns)
    unquoted_answer = _without_quoted_segments(answer)
    sentences = [part for part in _SENTENCE_BOUNDARY.split(unquoted_answer) if part.strip()]
    direct_match: str | None = None
    non_assertion_statuses: list[tuple[AssertionStatus, str]] = []
    for sentence in sentences:
        normalized_sentence = _normalize(sentence)
        for original, pattern in positive_patterns:
            if not _contains(normalized_sentence, pattern):
                continue
            context = _prefix_status(sentence, pattern)
            if context is None:
                direct_match = original
            else:
                non_assertion_statuses.append((context, original))

    if direct_match is not None:
        return FactAssertionAssessment(AssertionStatus.ASSERTED, True, direct_match)
    if non_assertion_statuses:
        status, matched = non_assertion_statuses[0]
        return FactAssertionAssessment(status, False, matched)
    if quoted_match:
        return FactAssertionAssessment(AssertionStatus.QUOTED, False)

    for original, pattern in _patterns(list(partial_patterns)):
        if _contains(normalized_answer, pattern):
            return FactAssertionAssessment(AssertionStatus.PARTIAL, False, original)

    overlap_status = _overlap_status(answer, positive_patterns)
    return FactAssertionAssessment(overlap_status, False)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dev_fact_index(dataset_path: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    fact_ids: list[str] = []
    facts: dict[str, dict[str, Any]] = {}
    for line in dataset_path.read_text(encoding="utf-8").splitlines():
        if not line or re.search(r'"split"\s*:\s*"dev"', line) is None:
            continue
        case = json.loads(line)
        if not case.get("answerable"):
            continue
        for fact in case.get("expected_facts", []):
            key = f"{case['case_id']}::{fact['fact_id']}"
            fact_ids.append(key)
            facts[key] = {"case": case, "fact": fact}
    return fact_ids, facts


def audit_scorer_v2(root: Path) -> dict[str, Any]:
    """Verify scorer fixtures bind exactly to DEV facts and frozen source bytes."""

    base = root / "evals/rag/v0.2/scorer-v2"
    manifest_path = base / "manifest.json"
    fixtures_path = base / "fixtures.json"
    spec_path = base / "spec.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    dataset_path = root / "evals/rag/v0.2/questions.jsonl"
    knowledge_manifest = root / "knowledge/novacommerce/manifest.json"

    if manifest.get("scorer_version") != "rag-v0.2-scorer-v2":
        raise ScorerV2Error("scorer version does not match the M5D-B2 contract")
    if manifest.get("fixture_data_sha256") != _sha256(fixtures_path):
        raise ScorerV2Error("scorer fixture SHA256 mismatch")
    if manifest.get("scorer_spec_path") != spec_path.relative_to(root).as_posix():
        raise ScorerV2Error("scorer specification path mismatch")
    if manifest.get("scorer_spec_sha256") != _sha256(spec_path):
        raise ScorerV2Error("scorer specification SHA256 mismatch")
    if spec.get("scorer_version") != manifest["scorer_version"]:
        raise ScorerV2Error("scorer specification version mismatch")
    spec_cues = spec.get("prefix_context", {})
    if (
        spec_cues.get("refusal_cues") != list(_REFUSAL_CUES)
        or spec_cues.get("uncertainty_cues") != list(_UNCERTAINTY_CUES)
        or spec_cues.get("negation_cues") != list(_NEGATION_CUES)
    ):
        raise ScorerV2Error("scorer implementation cue patterns differ from the frozen spec")
    if manifest.get("dataset_sha256") != _sha256(dataset_path):
        raise ScorerV2Error("scorer source dataset SHA256 mismatch")
    if manifest.get("knowledge_manifest_sha256") != _sha256(knowledge_manifest):
        raise ScorerV2Error("scorer source knowledge-manifest SHA256 mismatch")
    provenance = fixtures.get("provenance", {})
    manifest_provenance = manifest.get("fixture_provenance", {})
    if (
        provenance.get("candidate_outputs_consulted") != []
        or provenance.get("p2_p3_answer_text_used") is not False
        or provenance.get("p4_outputs_available") is not False
        or manifest_provenance.get("candidate_outputs_consulted") != []
        or manifest_provenance.get("p2_p3_answer_text_used") is not False
        or manifest_provenance.get("p4_outputs_available_during_construction") is not False
    ):
        raise ScorerV2Error("candidate outputs are disallowed scorer-v2 fixture sources")

    source_fact_ids, fact_index = _dev_fact_index(dataset_path)
    if manifest.get("source_fact_ids") != source_fact_ids:
        raise ScorerV2Error("scorer source fact IDs must match all answerable DEV facts")
    if len(source_fact_ids) != 72 or len(set(source_fact_ids)) != 72:
        raise ScorerV2Error("rag-v0.2 scorer-v2 requires the 72 answerable DEV facts")

    source_hashes = manifest.get("source_corpus_sha256", {})
    for relative_path, expected_sha in source_hashes.items():
        source_path = root / relative_path
        if not source_path.is_file() or _sha256(source_path) != expected_sha:
            raise ScorerV2Error(f"scorer source corpus hash mismatch: {relative_path}")

    fixture_keys: set[str] = set()
    for representative in fixtures.get("representative_facts", []):
        key = f"{representative['case_id']}::{representative['fact_id']}"
        if key not in fact_index:
            raise ScorerV2Error(f"fixture fact is not an answerable DEV fact: {key}")
        fixture_keys.add(key)
        source = fact_index[key]["fact"]
        if representative["statement"] != source["statement"]:
            raise ScorerV2Error(f"fixture statement differs from benchmark fact: {key}")
        if representative["benchmark_aliases"] != source["aliases"]:
            raise ScorerV2Error(f"fixture aliases differ from benchmark fact: {key}")
        locator = representative["supporting_locator"]
        if locator not in source["supporting_locators"]:
            raise ScorerV2Error(f"fixture locator differs from benchmark support: {key}")
        source_info = representative["source_corpus"]
        corpus_path = root / source_info["path"]
        if not corpus_path.is_file() or source_info["excerpt"] not in corpus_path.read_text(
            encoding="utf-8"
        ):
            raise ScorerV2Error(f"fixture source excerpt not found in corpus: {key}")
        if source_info["path"] not in source_hashes:
            raise ScorerV2Error(f"fixture source path lacks a manifest hash: {key}")

    return {
        "manifest": manifest,
        "fixtures": fixtures,
        "spec": spec,
        "representative_fact_keys": fixture_keys,
    }


__all__ = [
    "AssertionStatus",
    "FactAssertionAssessment",
    "ScorerV2Error",
    "audit_scorer_v2",
    "classify_labeled_fact_assertion",
]
