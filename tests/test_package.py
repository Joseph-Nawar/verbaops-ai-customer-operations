"""Smoke tests for the installed VerbaOps AI package foundation."""

import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import verbaops

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = PROJECT_ROOT / "src" / "verbaops"


def test_verbaops_imports_from_installed_src_package() -> None:
    """The import resolves to the installed project package in src layout."""
    assert verbaops.__file__ is not None
    package_path = Path(verbaops.__file__).resolve().parent

    assert package_path == SOURCE_PACKAGE.resolve()


def test_verbaops_version_matches_installed_distribution() -> None:
    """The package version comes from installed distribution metadata."""
    assert verbaops.__version__ == version("verbaops-ai") == "0.1.0"


def test_verbaops_does_not_depend_on_repository_root_pythonpath_hack() -> None:
    """No repository-root package shadows the installable src package."""
    assert verbaops.__file__ is not None
    assert not (PROJECT_ROOT / "verbaops").exists()
    assert Path(verbaops.__file__).resolve().is_relative_to(SOURCE_PACKAGE.resolve())


def test_old_package_name_is_not_importable_from_installed_environment() -> None:
    """The complete rename does not leave a compatibility import alias."""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "-c", "import relayai"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stderr
