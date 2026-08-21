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
    """Create or safely extend local VerbaOps and NovaCommerce development state."""

    env_path = root / ".env"
    password_path = root / ".secrets" / "postgres_password"
    commerce_password_path = root / ".secrets" / "commerce_postgres_password"
    env_exists = env_path.exists()
    password_exists = password_path.exists()
    if env_exists != password_exists:
        raise BootstrapError("VerbaOps local development configuration is incomplete")

    if env_exists and password_exists:
        password = password_path.read_text(encoding="utf-8").strip()
        env_content = env_path.read_text(encoding="utf-8")
        expected = f"VERBAOPS_DATABASE__URL=postgresql+asyncpg://verbaops:{password}@postgres:5432/verbaops"
        if not password or expected not in env_content:
            raise BootstrapError(
                "VerbaOps local development configuration has mismatched credentials"
            )
    else:
        if commerce_password_path.exists():
            raise BootstrapError("NovaCommerce secret exists without VerbaOps configuration")
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

    commerce_lines = {
        "environment": _setting_value(env_content, "NOVACOMMERCE_ENVIRONMENT"),
        "database_url": _setting_value(env_content, "NOVACOMMERCE_DATABASE__URL"),
        "log_level": _setting_value(env_content, "NOVACOMMERCE_OBSERVABILITY__LOG_LEVEL"),
    }
    commerce_config_present = "NOVACOMMERCE_" in env_content
    commerce_secret_exists = commerce_password_path.exists()
    if commerce_config_present != commerce_secret_exists:
        raise BootstrapError("NovaCommerce local development configuration is incomplete")

    if commerce_config_present:
        commerce_password = commerce_password_path.read_text(encoding="utf-8").strip()
        expected_commerce_url = (
            "postgresql+asyncpg://novacommerce:"
            f"{commerce_password}@commerce-postgres:5432/novacommerce"
        )
        if (
            not commerce_password
            or commerce_lines["environment"] != "development"
            or commerce_lines["database_url"] != expected_commerce_url
            or commerce_lines["log_level"] != "INFO"
        ):
            raise BootstrapError(
                "NovaCommerce local development configuration has mismatched credentials"
            )
    else:
        commerce_password = secrets.token_urlsafe(32)
        commerce_password_path.parent.mkdir(parents=True, exist_ok=True)
        _restrictive_write(commerce_password_path, commerce_password + "\n")
        if env_content and not env_content.endswith("\n"):
            env_content += "\n"
        env_content += "\n".join(
            [
                "NOVACOMMERCE_ENVIRONMENT=development",
                "NOVACOMMERCE_DATABASE__URL="
                f"postgresql+asyncpg://novacommerce:{commerce_password}@commerce-postgres:5432/novacommerce",
                "NOVACOMMERCE_OBSERVABILITY__LOG_LEVEL=INFO",
                "",
            ]
        )
        _restrictive_write(env_path, env_content)
    return env_path, password_path


def _setting_value(content: str, key: str) -> str | None:
    """Read one exact dotenv assignment without logging its value."""

    prefix = f"{key}="
    matches = [line[len(prefix) :] for line in content.splitlines() if line.startswith(prefix)]
    if len(matches) != 1:
        return None
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    bootstrap_dev_environment(args.root.resolve())


if __name__ == "__main__":
    main()
