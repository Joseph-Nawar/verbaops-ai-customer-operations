"""Structural rules for real PostgreSQL test marker classification."""

from collections.abc import Collection


def is_real_postgres_nodeid(nodeid: str) -> bool:
    path = nodeid.split("::", 1)[0].replace("\\", "/")
    return path.startswith("tests/integration/") and path.endswith("_postgres.py")


def validate_postgres_classification(nodeid: str, markers: Collection[str]) -> None:
    if not is_real_postgres_nodeid(nodeid):
        return

    marker_set = set(markers)
    if "postgres" not in marker_set:
        raise ValueError(f"{nodeid} must have the postgres marker")

    if "critical_race" in marker_set and "concurrency" not in marker_set:
        raise ValueError(f"{nodeid}: critical_race requires postgres and concurrency")

    categories = marker_set.intersection({"contract", "concurrency"})
    if len(categories) != 1:
        raise ValueError(f"{nodeid} must have exactly one of contract or concurrency")

    if "critical_race" in marker_set and "contract" in marker_set:
        raise ValueError(f"{nodeid}: critical_race cannot be combined with contract")
