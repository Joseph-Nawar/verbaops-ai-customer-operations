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
    assert password
    assert (
        f"VERBAOPS_DATABASE__URL=postgresql+asyncpg://verbaops:{password}@postgres:5432/verbaops"
        in env_text
    )
    assert capsys.readouterr().out == ""


def test_bootstrap_does_not_overwrite_existing_valid_configuration(tmp_path: Path) -> None:
    first = bootstrap_dev_environment(tmp_path)
    before = (first[0].read_text(), first[1].read_text())

    second = bootstrap_dev_environment(tmp_path)

    assert second == first
    assert (second[0].read_text(), second[1].read_text()) == before


def test_partial_bootstrap_state_fails_without_repairing_it(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("VERBAOPS_ENVIRONMENT=development\n", encoding="utf-8")

    with pytest.raises(BootstrapError):
        bootstrap_dev_environment(tmp_path)

    assert not (tmp_path / ".secrets" / "postgres_password").exists()
