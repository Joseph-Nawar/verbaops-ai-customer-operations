"""Create ignored local development configuration and a matching password."""

from __future__ import annotations

import argparse
import os
import secrets
from contextlib import suppress
from pathlib import Path


class BootstrapError(RuntimeError):
    """Raised when local development state is incomplete or inconsistent."""


def _restrictive_write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    with suppress(OSError):
        os.chmod(path, 0o600)


def bootstrap_dev_environment(root: Path) -> tuple[Path, Path]:
    """Create `.env` and `.secrets/postgres_password` only when both are absent."""

    env_path = root / ".env"
    password_path = root / ".secrets" / "postgres_password"
    env_exists = env_path.exists()
    password_exists = password_path.exists()
    if env_exists != password_exists:
        raise BootstrapError("local development configuration is incomplete")
    if env_exists and password_exists:
        password = password_path.read_text(encoding="utf-8").strip()
        expected = f"VERBAOPS_DATABASE__URL=postgresql+asyncpg://verbaops:{password}@postgres:5432/verbaops"
        if not password or expected not in env_path.read_text(encoding="utf-8"):
            raise BootstrapError("local development configuration has mismatched credentials")
        return env_path, password_path

    password = secrets.token_urlsafe(32)
    password_path.parent.mkdir(parents=True, exist_ok=True)
    _restrictive_write(password_path, password + "\n")
    env_content = "\n".join(
        [
            "VERBAOPS_ENVIRONMENT=development",
            f"VERBAOPS_DATABASE__URL=postgresql+asyncpg://verbaops:{password}@postgres:5432/verbaops",
            "VERBAOPS_REDIS__URL=redis://redis:6379/0",
            "VERBAOPS_OBSERVABILITY__LOG_LEVEL=INFO",
            "",
        ]
    )
    _restrictive_write(env_path, env_content)
    return env_path, password_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    bootstrap_dev_environment(args.root.resolve())


if __name__ == "__main__":
    main()
