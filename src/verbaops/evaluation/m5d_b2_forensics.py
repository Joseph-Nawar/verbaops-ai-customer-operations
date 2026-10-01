"""Provider-free case-level analysis of committed M5D-B DEV artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from verbaops.evaluation.rag_v02 import load_rag_v02_cases, recognize_labeled_fact_assertion
from verbaops.retrieval.grounding import SAFE_GROUNDING_FALLBACK

RUNS = {
    "P0_CURRENT": "canonical-M0-P0-20260929T124811Z-0d27c8d7",
    "P2_FAIL_CLOSED_CITATIONS": "canonical-M0-P2-20260930T135336Z-7c951350",
    "P3_ONE_REPAIR_THEN_FAIL_CLOSED": "canonical-M0-P3-20260930T165735Z-277d35de",
}
GATE_RUN = "canonical-gate-20260929T123626Z-45586c67"
GATE = "G2_TOP_EVIDENCE_CROSS_ENCODER"
THRESHOLD = 0.2554669
APPLICATION_SHA = "7f82c565e7f9fc085f2d81c2c04a9861444837a1"
HARNESS_SHA = "86c81196e7ed4c967eec62bfc2cab9484820529c"
POLICY_CATEGORIES = {"shipping", "returns", "refunds", "warranty", "payments", "privacy"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _locator(item: Any) -> str:
    if isinstance(item, str):
        return item
    return "|".join(
        str(item[key]) for key in ("document_slug", "document_version", "section", "chunk_index")
    )


def _terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if token
        not in {
            "a",
            "an",
            "the",
            "and",
            "or",
            "of",
            "to",
            "in",
            "on",
            "for",
            "is",
            "are",
            "be",
            "do",
            "does",
            "can",
            "will",
            "with",
            "from",
            "after",
            "before",
            "your",
            "you",
            "it",
            "this",
            "that",
        }
    }


def _same_answer(p2: dict[str, Any], p3: dict[str, Any]) -> bool:
    return bool(p2["final_answer"] == p3["final_answer"])


def _same_citations(p2: dict[str, Any], p3: dict[str, Any]) -> bool:
    return bool(p2["resolved_public_citations"] == p3["resolved_public_citations"])


def _same_fallback(p2: dict[str, Any], p3: dict[str, Any]) -> bool:
    return bool(p2["fallback_used"] == p3["fallback_used"])


def _same_recognition(p2: dict[str, Any], p3: dict[str, Any]) -> bool:
    return bool(p2["expected_fact_recognized"] == p3["expected_fact_recognized"])


def _same_support_citation(p2: dict[str, Any], p3: dict[str, Any]) -> bool:
    return bool(p2["citation_matches_expected_support"] == p3["citation_matches_expected_support"])


def _outcome(
    case: Any,
    record: dict[str, Any],
    gate: dict[str, Any],
    support: set[str],
    positive_judgments: set[str],
) -> dict[str, Any]:
    confidence = gate["gate_results"][GATE]["confidence"]
    accepted = confidence >= THRESHOLD
    final_five = [_locator(item) for item in gate["ranked_locators"][:5]]
    selected = [_locator(item) for item in record.get("selected_evidence", [])]
    citations = [_locator(item) for item in record.get("public_citations", [])]
    answer = str(record.get("final_answer", ""))
    fact = case.expected_facts[0] if case.expected_facts else None
    aliases = list(fact.aliases) if fact else []
    recognized = bool(fact and recognize_labeled_fact_assertion(answer, aliases))
    cited_support = sorted(set(citations) & support)
    cited_relevance = sorted(set(citations) & positive_judgments)
    citation_audit = [
        {
            "locator": citation,
            "positive_case_relevance": citation in positive_judgments,
            "expected_fact_support": citation in support,
            "in_supplied_evidence": citation in selected,
        }
        for citation in citations
    ]
    alias_terms = set().union(*(_terms(alias) for alias in aliases)) if aliases else set()
    answer_terms = _terms(answer)
    overlap = len(alias_terms & answer_terms) / len(alias_terms) if alias_terms else 0.0
    support_in_final_five = bool(set(final_five) & support)
    support_in_selected = bool(set(selected) & support)
    exact_fallback = answer.strip() == SAFE_GROUNDING_FALLBACK

    potential_recognition_gap = bool(
        not recognized
        and accepted
        and support_in_selected
        and overlap >= 0.7
        and cited_relevance
        and not exact_fallback
    )

    if recognized:
        if not citations:
            failure = "CITATION_MISSING"
        elif not cited_support:
            failure = "CITATION_WRONG_SUPPORT"
        else:
            failure = "NONE_EXPECTED_FACT_RECOGNIZED_AND_SUPPORT_CITED"
        uncertainty = (
            "Public citations are message-level locators; claim-span attachment is not recorded."
        )
    elif not support_in_final_five:
        failure = "RETRIEVAL_MISS"
        uncertainty = (
            "The expected supporting locator is absent from the committed final-five ranking."
        )
    elif not accepted:
        failure = "GATE_REJECTED_RELEVANT_EVIDENCE"
        uncertainty = "Relevant support appears in the final five, but the frozen G2 threshold rejects the turn."
    elif not support_in_selected:
        failure = "OTHER"
        uncertainty = "G2 accepts, but the observation does not show the expected support among supplied evidence."
    elif potential_recognition_gap:
        failure = "EVALUATOR_RECOGNITION_GAP"
        uncertainty = (
            "Review flag only: answer has high content-word overlap with the labeled fact and a relevant public citation, "
            "but the deterministic alias recognizer did not match it. This is not a rescored metric or a semantic truth judgment."
        )
    else:
        failure = "OTHER"
        uncertainty = (
            "Accepted supporting evidence is recorded, but raw pre-finalization model output is unavailable; "
            "generation omission, finalizer removal, and evaluator recognition gap cannot be separated from this artifact."
        )
        if exact_fallback:
            uncertainty += " Final answer is the deterministic safe fallback."

    return {
        "final_five_locators": final_five,
        "g2_accepted": accepted,
        "g2_confidence": confidence,
        "support_in_final_five": support_in_final_five,
        "support_in_accepted_evidence": support_in_selected,
        "selected_evidence_locators": selected,
        "raw_model_answer_available": False,
        "raw_model_answer": None,
        "final_answer": answer,
        "valid_citation_handles_emitted": None,
        "resolved_public_citations": citations,
        "citation_audit": citation_audit,
        "citation_count": len(citations),
        "positive_relevance_citation_count": sum(
            item["positive_case_relevance"] for item in citation_audit
        ),
        "expected_support_citation_count": sum(
            item["expected_fact_support"] for item in citation_audit
        ),
        "citation_outside_supplied_evidence_count": sum(
            not item["in_supplied_evidence"] for item in citation_audit
        ),
        "citation_matches_expected_support": bool(cited_support),
        "citation_matches_any_positive_judgment": bool(cited_relevance),
        "expected_fact_recognized": recognized,
        "case_level_expected_fact_citation_match": bool(recognized and cited_support),
        "tool_path_entered": bool(record.get("tool_call_count", 0)),
        "tool_names_available": False,
        "model_call_count": record.get("model_call_count"),
        "tool_call_count": record.get("tool_call_count"),
        "fallback_used": exact_fallback,
        "repair_attempted": bool(record.get("repair_attempted", False)),
        "repair_succeeded": bool(record.get("repair_succeeded", False)),
        "repair_failed_reason": record.get("repair_failed_reason"),
        "primary_failure_class": failure,
        "classification_uncertainty": uncertainty,
        "alias_content_term_overlap": round(overlap, 4),
        "potential_evaluator_recognition_gap_review_flag": potential_recognition_gap,
    }


def build_case_taxonomy(root: Path) -> list[dict[str, Any]]:
    dataset = root / "evals/rag/v0.2/questions.jsonl"
    cases = [
        case for case in load_rag_v02_cases(dataset) if case.split == "dev" and case.answerable
    ]
    artifacts = root / "evals/rag/v0.2/dev-evidence/canonical"
    gate_rows = _read_jsonl(artifacts / GATE_RUN / "gate_cases.jsonl")
    gate_by_case = {row["case_id"]: row for row in gate_rows}
    records = {
        candidate: {
            row["case_id"]: row for row in _read_jsonl(artifacts / run_id / "grounded_cases.jsonl")
        }
        for candidate, run_id in RUNS.items()
    }
    expected_fact_count = sum(len(case.expected_facts) for case in cases)
    if len(cases) != 72 or expected_fact_count != 72 or len(gate_by_case) != 96:
        raise ValueError("expected 72 answerable DEV cases and 96 gate observations")
    if any(len(records[candidate]) != 96 for candidate in RUNS):
        raise ValueError("each scored candidate must have exactly 96 records")

    result: list[dict[str, Any]] = []
    for case in cases:
        fact_records = []
        positive_judgments = {
            _locator(judgment.model_dump())
            for judgment in case.relevance_judgments
            if judgment.relevance_grade >= 1
        }
        for fact in case.expected_facts:
            support = {_locator(locator.model_dump()) for locator in fact.supporting_locators}
            case_support = set(support)
            outcomes = {
                candidate: _outcome(
                    case,
                    records[candidate][case.case_id],
                    gate_by_case[case.case_id],
                    case_support,
                    positive_judgments,
                )
                for candidate in RUNS
            }
            fact_records.append(
                {
                    "fact_id": fact.fact_id,
                    "expected_fact": fact.statement,
                    "aliases": list(fact.aliases),
                    "expected_supporting_locators": sorted(support),
                    "candidate_outcomes": outcomes,
                }
            )
        gate_row = gate_by_case[case.case_id]
        result.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "query": case.query,
                "expected_facts": fact_records,
                "g2_confidence": gate_row["gate_results"][GATE]["confidence"],
                "g2_accepted": gate_row["gate_results"][GATE]["confidence"] >= THRESHOLD,
                "retrieved_final_five_locators": [
                    _locator(item) for item in gate_row["ranked_locators"][:5]
                ],
                "positive_relevance_locators": sorted(positive_judgments),
                "expected_support_present_in_final_five": any(
                    set(fact["expected_supporting_locators"])
                    & {_locator(item) for item in gate_row["ranked_locators"][:5]}
                    for fact in fact_records
                ),
            }
        )
    return result


def summarize_taxonomy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"answerable_cases": len(rows), "candidates": {}}
    summary["retrieval_and_gate"] = {
        "support_absent_from_final_five": sum(
            not row["expected_support_present_in_final_five"] for row in rows
        ),
        "support_present_in_final_five": sum(
            row["expected_support_present_in_final_five"] for row in rows
        ),
        "g2_accepted": sum(row["g2_accepted"] for row in rows),
        "support_present_and_g2_accepted": sum(
            row["expected_support_present_in_final_five"] and row["g2_accepted"] for row in rows
        ),
    }
    for candidate in RUNS:
        outcomes = [
            fact["candidate_outcomes"][candidate] for row in rows for fact in row["expected_facts"]
        ]
        accepted = [
            out
            for row in rows
            if row["g2_accepted"]
            for fact in row["expected_facts"]
            for out in [fact["candidate_outcomes"][candidate]]
        ]
        failure_counts = Counter(out["primary_failure_class"] for out in outcomes)
        recognized = sum(out["expected_fact_recognized"] for out in outcomes)
        cited = sum(out["case_level_expected_fact_citation_match"] for out in outcomes)
        citation_count = sum(out["citation_count"] for out in outcomes)
        positive_citation_count = sum(out["positive_relevance_citation_count"] for out in outcomes)
        policy_tool_cases = sum(
            case["category"] in POLICY_CATEGORIES
            and case["expected_facts"][0]["candidate_outcomes"][candidate]["tool_path_entered"]
            for case in rows
        )
        all_tool_cases = sum(out["tool_path_entered"] for out in outcomes)
        summary["candidates"][candidate] = {
            "expected_fact_denominator": len(outcomes),
            "expected_fact_recognized": recognized,
            "recognized_fact_with_support_citation": cited,
            "expected_support_locator_cited_cases": sum(
                out["citation_matches_expected_support"] for out in outcomes
            ),
            "expected_support_locator_cited_case_ids": [
                row["case_id"]
                for row in rows
                if row["expected_facts"][0]["candidate_outcomes"][candidate][
                    "citation_matches_expected_support"
                ]
            ],
            "fallback_cases": sum(out["fallback_used"] for out in outcomes),
            "tool_using_answerable_cases": all_tool_cases,
            "policy_category_tool_cases": policy_tool_cases,
            "policy_category_tool_case_ids": [
                case["case_id"]
                for case in rows
                if case["category"] in POLICY_CATEGORIES
                and case["expected_facts"][0]["candidate_outcomes"][candidate]["tool_path_entered"]
            ],
            "tool_invocation_count_answerable": sum(
                out["tool_call_count"] or 0 for out in outcomes
            ),
            "tool_using_accepted_answerable_cases": sum(
                out["tool_path_entered"] for out in accepted
            ),
            "support_selected_accepted": sum(
                out["support_in_accepted_evidence"] for out in accepted
            ),
            "accepted_not_recognized_by_frozen_evaluator": sum(
                not out["expected_fact_recognized"] for out in accepted
            ),
            "recognized_without_expected_support_citation": sum(
                out["expected_fact_recognized"] and not out["citation_matches_expected_support"]
                for out in accepted
            ),
            "accepted_fallbacks": sum(out["fallback_used"] for out in accepted),
            "potential_evaluator_recognition_gap_review_flags": sum(
                out["potential_evaluator_recognition_gap_review_flag"] for out in outcomes
            ),
            "citation_precision_answerable_only": {
                "numerator": positive_citation_count,
                "denominator": citation_count,
                "value": positive_citation_count / citation_count if citation_count else None,
            },
            "failure_class_counts": dict(sorted(failure_counts.items())),
        }
    category_summary: dict[str, Any] = {}
    for category in sorted({row["category"] for row in rows}):
        category_rows = [row for row in rows if row["category"] == category]
        category_summary[category] = {"answerable_cases": len(category_rows), "candidates": {}}
        for candidate in RUNS:
            outcomes = [
                row["expected_facts"][0]["candidate_outcomes"][candidate] for row in category_rows
            ]
            category_summary[category]["candidates"][candidate] = {
                "recognized_expected_facts": sum(
                    out["expected_fact_recognized"] for out in outcomes
                ),
                "support_locator_cited_cases": sum(
                    out["citation_matches_expected_support"] for out in outcomes
                ),
                "potential_recognition_gap_review_flags": sum(
                    out["potential_evaluator_recognition_gap_review_flag"] for out in outcomes
                ),
                "fallback_cases": sum(out["fallback_used"] for out in outcomes),
                "tool_using_cases": sum(out["tool_path_entered"] for out in outcomes),
            }
    summary["category_breakdown"] = category_summary
    return summary


def build_extended_analysis(root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    all_cases = [
        case
        for case in load_rag_v02_cases(root / "evals/rag/v0.2/questions.jsonl")
        if case.split == "dev"
    ]
    by_case = {case.case_id: case for case in all_cases}
    artifacts = root / "evals/rag/v0.2/dev-evidence/canonical"
    all_records = {
        candidate: {
            record["case_id"]: record
            for record in _read_jsonl(artifacts / run_id / "grounded_cases.jsonl")
        }
        for candidate, run_id in RUNS.items()
    }
    citation_stats: dict[str, Any] = {}
    for candidate, records in all_records.items():
        total = positive = outside_evidence = expected_support = 0
        nonpositive_locators: Counter[str] = Counter()
        citations_on_answerable = citations_on_no_answer = 0
        for case_id, record in records.items():
            case = by_case[case_id]
            judged = {
                _locator(item.model_dump())
                for item in case.relevance_judgments
                if item.relevance_grade >= 1
            }
            supports = {
                _locator(locator.model_dump())
                for fact in case.expected_facts
                for locator in fact.supporting_locators
            }
            supplied = {_locator(item) for item in record.get("selected_evidence", [])}
            citations = [_locator(item) for item in record.get("public_citations", [])]
            citations_on_answerable += len(citations) if case.answerable else 0
            citations_on_no_answer += len(citations) if not case.answerable else 0
            total += len(citations)
            positive += sum(citation in judged for citation in citations)
            expected_support += sum(citation in supports for citation in citations)
            outside_evidence += sum(citation not in supplied for citation in citations)
            nonpositive_locators.update(
                citation for citation in citations if citation not in judged
            )
        citation_stats[candidate] = {
            "all_dev_citations": total,
            "positive_case_relevance": positive,
            "nonpositive_or_unjudged": total - positive,
            "precision": positive / total if total else None,
            "citations_on_answerable_cases": citations_on_answerable,
            "citations_on_no_answer_cases": citations_on_no_answer,
            "citations_matching_expected_support": expected_support,
            "citations_outside_supplied_evidence": outside_evidence,
            "most_common_nonpositive_locators": nonpositive_locators.most_common(10),
            "handle_or_unresolved_citation_evidence_available": False,
        }

    comparison_fields: dict[str, Callable[[dict[str, Any], dict[str, Any]], bool]] = {
        "answer_same": _same_answer,
        "citation_locators_same": _same_citations,
        "fallback_same": _same_fallback,
        "fact_recognition_same": _same_recognition,
        "support_citation_same": _same_support_citation,
    }
    comparisons: dict[str, Any] = {}
    for key, predicate in comparison_fields.items():
        comparisons[key] = sum(
            predicate(
                row["expected_facts"][0]["candidate_outcomes"]["P2_FAIL_CLOSED_CITATIONS"],
                row["expected_facts"][0]["candidate_outcomes"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"],
            )
            for row in rows
        )
    comparisons["answer_changed_case_ids"] = [
        row["case_id"]
        for row in rows
        if not comparison_fields["answer_same"](
            row["expected_facts"][0]["candidate_outcomes"]["P2_FAIL_CLOSED_CITATIONS"],
            row["expected_facts"][0]["candidate_outcomes"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"],
        )
    ]
    comparisons["citation_changed_case_ids"] = [
        row["case_id"]
        for row in rows
        if not comparison_fields["citation_locators_same"](
            row["expected_facts"][0]["candidate_outcomes"]["P2_FAIL_CLOSED_CITATIONS"],
            row["expected_facts"][0]["candidate_outcomes"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"],
        )
    ]
    comparisons["recognized_fact_case_ids_p2_only"] = []
    comparisons["recognized_fact_case_ids_p3_only"] = [
        row["case_id"]
        for row in rows
        if row["expected_facts"][0]["candidate_outcomes"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"][
            "expected_fact_recognized"
        ]
        and not row["expected_facts"][0]["candidate_outcomes"]["P2_FAIL_CLOSED_CITATIONS"][
            "expected_fact_recognized"
        ]
    ]
    comparisons["expected_support_citation_changed_case_ids"] = [
        row["case_id"]
        for row in rows
        if not comparison_fields["support_citation_same"](
            row["expected_facts"][0]["candidate_outcomes"]["P2_FAIL_CLOSED_CITATIONS"],
            row["expected_facts"][0]["candidate_outcomes"]["P3_ONE_REPAIR_THEN_FAIL_CLOSED"],
        )
    ]

    p3 = all_records["P3_ONE_REPAIR_THEN_FAIL_CLOSED"]
    repair_rows = [record for record in p3.values() if record.get("repair_attempted")]
    repair_cases = []
    for record in repair_rows:
        case_id = record["case_id"]
        case = by_case[case_id]
        p2_record = all_records["P2_FAIL_CLOSED_CITATIONS"][case_id]
        repair_cases.append(
            {
                "case_id": case_id,
                "category": case.category,
                "answerable": case.answerable,
                "repair_succeeded": bool(record.get("repair_succeeded")),
                "repair_failed_reason": record.get("repair_failed_reason"),
                "p2_final_answer_was_fallback": p2_record.get("final_answer", "").strip()
                == SAFE_GROUNDING_FALLBACK,
                "p3_final_answer_is_fallback": record.get("final_answer", "").strip()
                == SAFE_GROUNDING_FALLBACK,
                "p2_citations": p2_record.get("public_citations", []),
                "p3_citations": record.get("public_citations", []),
                "p3_model_calls": record.get("model_call_count"),
            }
        )
    p3_expected_support = sum(case.answerable for case in all_cases)
    input_paths = [
        Path("evals/rag/v0.2/questions.jsonl"),
        Path("evals/rag/v0.2/manifest.json"),
        Path("evals/rag/v0.2/experiment-plan.json"),
        Path("evals/rag/v0.2/dev-decision.json"),
        Path("evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json"),
        Path("docs/evaluation/stage5-m5d-b-dev-results.md"),
        Path("evals/rag/v0.2/dev-evidence/canonical") / GATE_RUN / "gate_cases.jsonl",
        Path("evals/rag/v0.2/dev-evidence/canonical") / GATE_RUN / "gate-report.json",
    ]
    for run_id in RUNS.values():
        input_paths.extend(
            [
                Path("evals/rag/v0.2/dev-evidence/canonical") / run_id / "grounded_cases.jsonl",
                Path("evals/rag/v0.2/dev-evidence/canonical") / run_id / "report.json",
            ]
        )
    tool_paths = [
        Path("src/verbaops/evaluation/m5d_b2_forensics.py"),
        Path("scripts/analyze_m5d_b2_forensics.py"),
    ]

    return {
        "provenance": {
            "application_under_test_sha": APPLICATION_SHA,
            "evaluation_harness_sha": HARNESS_SHA,
            "selected_gate": GATE,
            "threshold": THRESHOLD,
            "split": "dev",
            "release_holdout_executed": False,
            "selection_json_present": (root / "evals/rag/v0.2/selection.json").exists(),
            "provider_calls_made": False,
            "input_artifacts": [
                {"path": path.as_posix(), "sha256": _sha256(root / path)} for path in input_paths
            ],
            "forensics_tool_sha256": {path.as_posix(): _sha256(root / path) for path in tool_paths},
        },
        "candidate_citation_audit": citation_stats,
        "p2_vs_p3_answerable_case_delta": comparisons,
        "p3_repair_audit": {
            "attempts_all_dev": len(repair_rows),
            "successes_all_dev": sum(
                bool(record.get("repair_succeeded")) for record in repair_rows
            ),
            "failures_all_dev": sum(
                not bool(record.get("repair_succeeded")) for record in repair_rows
            ),
            "answerable_case_attempts": sum(item["answerable"] for item in repair_cases),
            "answerable_case_successes": sum(
                item["answerable"] and item["repair_succeeded"] for item in repair_cases
            ),
            "answerable_case_failures": sum(
                item["answerable"] and not item["repair_succeeded"] for item in repair_cases
            ),
            "cases": repair_cases,
        },
        "evidence_gate": {
            "selected_gate": GATE,
            "threshold": THRESHOLD,
            "answerable_cases": p3_expected_support,
            "accepted_answerable": sum(row["g2_accepted"] for row in rows),
            "positive_support_final_five": sum(
                row["expected_support_present_in_final_five"] for row in rows
            ),
            "accepted_with_positive_support": sum(
                row["expected_support_present_in_final_five"] and row["g2_accepted"] for row in rows
            ),
            "rejected_with_positive_support": sum(
                row["expected_support_present_in_final_five"] and not row["g2_accepted"]
                for row in rows
            ),
        },
        "trace_visibility_limitations": [
            "Canonical case records include final answers, resolved public citation locators, model/tool call counts, and aggregate repair fields.",
            "Raw pre-finalization model answers, tool names/arguments/results, unresolved citation handles, and claim-span citation attachment are not present in the committed case artifacts.",
            "Therefore generation omission versus finalizer removal cannot be resolved, and tool invocation can be counted but not named or semantically attributed from these artifacts alone.",
        ],
    }


def write_analysis(root: Path, output_dir: Path) -> tuple[Path, Path, Path]:
    rows = build_case_taxonomy(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    case_path = output_dir / "m5d-b2-case-taxonomy.jsonl"
    summary_path = output_dir / "m5d-b2-forensic-aggregates.json"
    extended_path = output_dir / "m5d-b2-delta-and-citation-audit.json"
    case_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    summary_path.write_text(
        json.dumps(summarize_taxonomy(rows), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    extended_path.write_text(
        json.dumps(
            build_extended_analysis(root, rows), ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return case_path, summary_path, extended_path


__all__ = [
    "RUNS",
    "build_case_taxonomy",
    "build_extended_analysis",
    "summarize_taxonomy",
    "write_analysis",
]
