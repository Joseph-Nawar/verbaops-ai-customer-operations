"""Tests for local-only development secret bootstrap."""

from pathlib import Path

import pytest
from scripts.bootstrap_dev_env import BootstrapError, bootstrap_dev_environment


def test_fresh_bootstrap_creates_matching_ignored_artifacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_path, password_path = bootstrap_dev_environment(tmp_path)

    env_text = env_path.read_text(encoding="utf-8")
    password = password_path.read_text(encoding="utf-8").strip()
    commerce_password_path = tmp_path / ".secrets" / "commerce_postgres_password"
    commerce_password = commerce_password_path.read_text(encoding="utf-8").strip()
    assert password
    assert commerce_password
    assert (
        f"VERBAOPS_DATABASE__URL=postgresql+asyncpg://verbaops:{password}@postgres:5432/verbaops"
        in env_text
    )
    assert (
        f"NOVACOMMERCE_DATABASE__URL=postgresql+asyncpg://novacommerce:{commerce_password}"
        "@commerce-postgres:5432/novacommerce" in env_text
    )
    assert capsys.readouterr().out == ""


def test_bootstrap_does_not_overwrite_existing_valid_configuration(tmp_path: Path) -> None:
    first = bootstrap_dev_environment(tmp_path)
    commerce_password_path = tmp_path / ".secrets" / "commerce_postgres_password"
    before = (first[0].read_text(), first[1].read_text(), commerce_password_path.read_text())

    second = bootstrap_dev_environment(tmp_path)

    assert second == first
    assert (
        second[0].read_text(),
        second[1].read_text(),
        commerce_password_path.read_text(),
    ) == before


def test_bootstrap_upgrades_existing_stage1_without_replacing_its_secret(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    password_path = tmp_path / ".secrets" / "postgres_password"
    password_path.parent.mkdir()
    password_path.write_text("stage1-secret\n", encoding="utf-8")
    original = "\n".join(
        [
            "VERBAOPS_ENVIRONMENT=development",
            "VERBAOPS_DATABASE__URL=postgresql+asyncpg://verbaops:stage1-secret@postgres:5432/verbaops",
            "VERBAOPS_REDIS__URL=redis://redis:6379/0",
            "VERBAOPS_OBSERVABILITY__LOG_LEVEL=INFO",
            "",
        ]
    )
    env_path.write_text(original, encoding="utf-8")

    bootstrap_dev_environment(tmp_path)

    assert password_path.read_text(encoding="utf-8") == "stage1-secret\n"
    upgraded = env_path.read_text(encoding="utf-8")
    assert original.rstrip() in upgraded
    assert "NOVACOMMERCE_ENVIRONMENT=development" in upgraded
    assert (tmp_path / ".secrets" / "commerce_postgres_password").exists()


@pytest.mark.parametrize(
    ("secret_exists", "config_line"),
    [
        (True, None),
        (
            False,
            "NOVACOMMERCE_DATABASE__URL=postgresql+asyncpg://novacommerce:secret@commerce-postgres:5432/novacommerce",
        ),
    ],
)
def test_partial_commerce_configuration_fails_without_repairing_it(
    tmp_path: Path,
    secret_exists: bool,
    config_line: str | None,
) -> None:
    env_path = tmp_path / ".env"
    password_path = tmp_path / ".secrets" / "postgres_password"
    password_path.parent.mkdir()
    password_path.write_text("stage1-secret\n", encoding="utf-8")
    content = "VERBAOPS_ENVIRONMENT=development\nVERBAOPS_DATABASE__URL=postgresql+asyncpg://verbaops:stage1-secret@postgres:5432/verbaops\n"
    if config_line:
        content += config_line + "\n"
    env_path.write_text(content, encoding="utf-8")
    commerce_path = tmp_path / ".secrets" / "commerce_postgres_password"
    if secret_exists:
        commerce_path.write_text("commerce-secret\n", encoding="utf-8")

    with pytest.raises(BootstrapError):
        bootstrap_dev_environment(tmp_path)


def test_partial_bootstrap_state_fails_without_repairing_it(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("VERBAOPS_ENVIRONMENT=development\n", encoding="utf-8")

    with pytest.raises(BootstrapError):
        bootstrap_dev_environment(tmp_path)

    assert not (tmp_path / ".secrets" / "postgres_password").exists()
