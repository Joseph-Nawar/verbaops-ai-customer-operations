"""Smoke tests for the installed RelayAI package foundation."""

from importlib.metadata import version
from pathlib import Path

import relayai

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = PROJECT_ROOT / "src" / "relayai"


def test_relayai_imports_from_installed_src_package() -> None:
    """The import resolves to the installed project package in src layout."""
    assert relayai.__file__ is not None
    package_path = Path(relayai.__file__).resolve().parent

    assert package_path == SOURCE_PACKAGE.resolve()


def test_relayai_version_matches_installed_distribution() -> None:
    """The package version comes from installed distribution metadata."""
    assert relayai.__version__ == version("relay-ai") == "0.1.0"


def test_relayai_does_not_depend_on_repository_root_pythonpath_hack() -> None:
    """No repository-root package shadows the installable src package."""
    assert relayai.__file__ is not None
    assert not (PROJECT_ROOT / "relayai").exists()
    assert Path(relayai.__file__).resolve().is_relative_to(SOURCE_PACKAGE.resolve())
