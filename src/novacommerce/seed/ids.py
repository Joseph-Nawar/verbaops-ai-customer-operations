"""Stable UUIDv5 helpers for seeded rows and named scenarios."""

from uuid import UUID, uuid5

from novacommerce.seed.config import SeedConfig
from novacommerce.seed.scenarios import SCENARIO_ENTITY_TYPES, SeedScenario

NOVA_COMMERCE_SEED_NAMESPACE = UUID("4b5f7bbf-8cb2-5c87-8b6d-9a7f35e65a4f")


def deterministic_uuid(seed: int, entity_type: str, stable_key: str) -> UUID:
    """Return a UUIDv5 derived only from explicit seed identity inputs."""

    return uuid5(NOVA_COMMERCE_SEED_NAMESPACE, f"{seed}:{entity_type}:{stable_key}")


def scenario_uuid(config: SeedConfig, scenario: SeedScenario | str) -> UUID:
    """Return the deterministic ID reserved for a named scenario row."""

    scenario_value = scenario.value if isinstance(scenario, SeedScenario) else scenario
    return deterministic_uuid(config.seed, SCENARIO_ENTITY_TYPES[scenario_value], scenario_value)
