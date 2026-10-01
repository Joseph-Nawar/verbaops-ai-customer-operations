"""Fixture and frozen-contract audit wrapper for scorer-v2."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from verbaops.evaluation.rag_v02_scorer_impl import (
    _NEGATION_CUES,
    _REFUSAL_CUES,
    _UNCERTAINTY_CUES,
)


class ScorerV2Error(ValueError):
    """Raised when the frozen scorer fixtures or provenance do not validate."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_file_sha256(path: Path, expected: str, artifact: str) -> None:
    if not path.is_file() or _sha256(path) != expected:
        raise ScorerV2Error(f"{artifact} SHA256 mismatch")


def _bound_repo_path(root: Path, relative_path: Any, artifact: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ScorerV2Error(f"{artifact} path is missing")
    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or ".." in pure_path.parts or "\\" in relative_path:
        raise ScorerV2Error(f"{artifact} path must be a normalized repository-relative path")
    path = root.joinpath(*pure_path.parts)
    if path.relative_to(root).as_posix() != relative_path:
        raise ScorerV2Error(f"{artifact} path must be a normalized repository-relative path")
    return path


def _dev_fact_index(dataset_path: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    fact_ids: list[str] = []
    facts: dict[str, dict[str, Any]] = {}
    with dataset_path.open(encoding="utf-8") as dataset:
        lines = iter(dataset)
        for line in lines:
            if re.search(r'"split"\s*:\s*"dev"', line) is None:
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

    if (
        manifest.get("schema_version") != "m5d-b2-scorer-v2-manifest-v2"
        or manifest.get("scorer_version") != "rag-v0.2-scorer-v2"
    ):
        raise ScorerV2Error("scorer version does not match the M5D-B2 contract")
    frozen_sha = manifest.get("scorer_frozen_at_commit_sha")
    if (
        not isinstance(frozen_sha, str)
        or not re.fullmatch(r"[a-f0-9]{40}", frozen_sha)
        or frozen_sha == "c8a55e63c20e209d7ee920c3020977d001b41a1b"
    ):
        raise ScorerV2Error("scorer manifest must bind a committed definition SHA")
    if manifest.get("fixture_data_path") != fixtures_path.relative_to(root).as_posix():
        raise ScorerV2Error("scorer fixture path mismatch")
    implementation_path = _bound_repo_path(
        root, manifest.get("scorer_implementation_path"), "scorer implementation"
    )
    if (
        manifest.get("scorer_implementation_path")
        != implementation_path.relative_to(root).as_posix()
    ):
        raise ScorerV2Error("scorer implementation path mismatch")
    if manifest.get("scorer_entrypoint") != (
        "verbaops.evaluation.rag_v02_scorer_impl.classify_labeled_fact_assertion"
    ):
        raise ScorerV2Error("scorer entrypoint differs from the frozen implementation")
    _assert_file_sha256(
        implementation_path,
        manifest.get("scorer_implementation_sha256", ""),
        "scorer implementation",
    )
    _assert_file_sha256(fixtures_path, manifest.get("fixture_data_sha256", ""), "scorer fixture")
    if manifest.get("scorer_spec_path") != spec_path.relative_to(root).as_posix():
        raise ScorerV2Error("scorer specification path mismatch")
    _assert_file_sha256(spec_path, manifest.get("scorer_spec_sha256", ""), "scorer specification")
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
        or provenance.get("paraphrases_independently_authored_from_fact_and_source") is not True
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

    knowledge_index = json.loads(knowledge_manifest.read_text(encoding="utf-8"))
    corpus_paths = {
        (document["slug"], document["version"]): (
            Path("knowledge/novacommerce") / document["path"]
        ).as_posix()
        for document in knowledge_index["documents"]
    }

    source_hashes = manifest.get("source_corpus_sha256", {})
    fixture_facts = fixtures.get("facts", [])
    fixture_keys = [f"{fact['case_id']}::{fact['fact_id']}" for fact in fixture_facts]
    if (
        fixture_keys != source_fact_ids
        or len(set(fixture_keys)) != len(fixture_keys)
        or manifest.get("fixture_fact_count") != 72
        or manifest.get("authored_positive_paraphrase_count")
        != sum(len(fact.get("positive_paraphrases", [])) for fact in fixture_facts)
    ):
        raise ScorerV2Error("scorer fixture facts must exactly match all answerable DEV facts")

    fixture_source_paths: set[str] = set()
    for fact_fixture in fixture_facts:
        key = f"{fact_fixture['case_id']}::{fact_fixture['fact_id']}"
        if key not in fact_index:
            raise ScorerV2Error(f"fixture fact is not an answerable DEV fact: {key}")
        source = fact_index[key]["fact"]
        if fact_fixture.get("statement") != source["statement"]:
            raise ScorerV2Error(f"fixture statement differs from benchmark fact: {key}")
        if fact_fixture.get("benchmark_aliases") != source["aliases"]:
            raise ScorerV2Error(f"fixture aliases differ from benchmark fact: {key}")
        locator = fact_fixture.get("supporting_locator")
        if locator not in source["supporting_locators"]:
            raise ScorerV2Error(f"fixture locator differs from benchmark support: {key}")
        if not isinstance(locator, dict):
            raise ScorerV2Error(f"fixture supporting locator is invalid: {key}")
        expected_source_path = corpus_paths.get(
            (locator.get("document_slug"), locator.get("document_version"))
        )
        source_info = fact_fixture.get("source_corpus", {})
        if source_info.get("path") != expected_source_path:
            raise ScorerV2Error(f"fixture source path does not match its document locator: {key}")
        source_path = source_info.get("path")
        if not isinstance(source_path, str) or not source_path:
            raise ScorerV2Error(f"fixture source path is missing: {key}")
        fixture_source_paths.add(source_path)
        corpus_path = _bound_repo_path(root, source_path, "scorer source corpus")
        excerpt = source_info.get("excerpt")
        if (
            not isinstance(excerpt, str)
            or not excerpt.strip()
            or not corpus_path.is_file()
            or excerpt not in corpus_path.read_text(encoding="utf-8")
        ):
            raise ScorerV2Error(f"fixture source excerpt not found in corpus: {key}")
        paraphrases = fact_fixture.get("positive_paraphrases")
        if (
            not isinstance(paraphrases, list)
            or not paraphrases
            or any(
                not isinstance(paraphrase, str) or not paraphrase.strip()
                for paraphrase in paraphrases
            )
        ):
            raise ScorerV2Error(f"fixture fact requires an authored positive paraphrase: {key}")
        if fact_fixture.get("paraphrase_provenance") != (
            "Independently authored from this benchmark fact and its hash-bound supporting corpus "
            "excerpt; no candidate output consulted."
        ):
            raise ScorerV2Error(f"fixture paraphrase provenance is missing or invalid: {key}")
        if source_path not in source_hashes:
            raise ScorerV2Error(f"fixture source path lacks a manifest hash: {key}")

    if set(source_hashes) != fixture_source_paths:
        raise ScorerV2Error("source-corpus hashes must exactly cover fixture evidence files")
    for relative_path, expected_sha in source_hashes.items():
        source_path = _bound_repo_path(root, relative_path, "scorer source corpus")
        _assert_file_sha256(source_path, expected_sha, f"source corpus {relative_path}")

    matrix_provenance = fixtures.get("negative_matrix_provenance", {})
    if (
        matrix_provenance.get("candidate_outputs_consulted") != []
        or matrix_provenance.get("p2_p3_answer_text_used") is not False
        or matrix_provenance.get("p4_outputs_available") is not False
    ):
        raise ScorerV2Error("candidate outputs are disallowed negative-fixture sources")

    return {
        "manifest": manifest,
        "fixtures": fixtures,
        "spec": spec,
        "fixture_fact_keys": set(fixture_keys),
    }


__all__ = [
    "ScorerV2Error",
    "audit_scorer_v2",
]
