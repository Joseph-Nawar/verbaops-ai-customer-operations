"""Require an explicitly supplied disposable PostgreSQL integration URL."""

import os
import sys


def main() -> int:
    value = os.environ.get("NOVACOMMERCE_TEST_DATABASE_URL", "")
    if not value:
        print("NOVACOMMERCE_TEST_DATABASE_URL is required for PostgreSQL targets.", file=sys.stderr)
        return 2
    if not value.startswith("postgresql+asyncpg://"):
        print(
            "NOVACOMMERCE_TEST_DATABASE_URL must use postgresql+asyncpg://.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
