"""NovaCommerce package installation contract tests."""

from importlib.metadata import version

import novacommerce


def test_novacommerce_version_matches_distribution_metadata() -> None:
    assert novacommerce.__version__ == version("verbaops-ai") == "0.1.0"
