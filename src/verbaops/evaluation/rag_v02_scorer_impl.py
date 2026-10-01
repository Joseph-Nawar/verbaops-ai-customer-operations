"""Frozen deterministic fact-assertion recognition implementation for M5D-B2."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


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
