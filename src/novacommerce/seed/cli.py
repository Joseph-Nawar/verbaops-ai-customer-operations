"""Command-line entry point for deterministic NovaCommerce development data."""

from __future__ import annotations

import argparse
import asyncio
import json

from novacommerce.config.settings import Settings
from novacommerce.seed.config import DEFAULT_AS_OF, DEFAULT_SEED, SeedConfig, parse_as_of
from novacommerce.seed.service import SeedServiceError, seed_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--as-of", type=parse_as_of, default=DEFAULT_AS_OF)
    parser.add_argument(
        "--reset", action="store_true", help="clear application data before seeding"
    )
    return parser


async def run(arguments: argparse.Namespace) -> None:
    result = await seed_database(
        Settings(),
        SeedConfig(seed=arguments.seed, as_of=arguments.as_of),
        reset=arguments.reset,
    )
    print(
        json.dumps(
            {
                "seed": result.seed,
                "as_of": result.as_of,
                "counts": result.counts,
                "fingerprint": result.fingerprint,
                "scenario_ids": result.scenario_ids,
            },
            sort_keys=True,
        )
    )


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        asyncio.run(run(arguments))
    except SeedServiceError as error:
        print(f"seed refused: {error}")
        return 1
    return 0
