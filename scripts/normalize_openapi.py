"""Generate and check the normalized NovaCommerce /v1 OpenAPI contract."""

import argparse
import difflib
from pathlib import Path

from pydantic import SecretStr

from novacommerce.api.app import create_app
from novacommerce.config.settings import Environment, Settings
from scripts.openapi_contract import normalize_openapi, normalized_bytes

__all__ = ["normalize_openapi", "normalized_bytes"]


def generate_normalized_openapi() -> bytes:
    """Generate the contract from the real FastAPI application without starting I/O."""

    settings = Settings(
        environment=Environment.TEST,
        service_token=SecretStr("m2e-contract-test-token-" + "x" * 32),
    )
    app = create_app(settings=settings)
    return normalized_bytes(app.openapi())


def _check(path: Path) -> int:
    expected = path.read_bytes() if path.exists() else b""
    actual = generate_normalized_openapi()
    if actual == expected:
        print(f"OpenAPI contract is up to date: {path}")
        return 0
    print(f"OpenAPI contract differs: {path}")
    diff = difflib.unified_diff(
        expected.decode("utf-8", errors="replace").splitlines(),
        actual.decode("utf-8").splitlines(),
        fromfile=str(path),
        tofile="generated",
        lineterm="",
    )
    print("\n".join(list(diff)[:120]))
    return 1


def _update(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(generate_normalized_openapi())
    print(f"Updated OpenAPI contract: {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--update", action="store_true")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    return _check(args.path) if args.check else _update(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
