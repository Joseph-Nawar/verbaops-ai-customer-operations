"""Contract tests for the additive NovaCommerce local stack."""

import re
from pathlib import Path


def compose_text() -> str:
    return Path("docker-compose.yml").read_text(encoding="utf-8")


def test_compose_keeps_m2a_services_and_adds_profile_gated_seed_service() -> None:
    text = compose_text()
    for service in ("commerce-postgres:", "commerce-migrate:", "commerce-api:"):
        assert len(re.findall(rf"^  {re.escape(service)}$", text, re.MULTILINE)) == 1
    assert "commerce-postgres:" in text
    assert "commerce-migrate:" in text
    assert "commerce-api:" in text
    assert "commerce_postgres_data" in text
    assert '"8010:8000"' in text
    assert "commerce_postgres_password" in text
    assert "service_completed_successfully" in text
    assert "alembic-commerce.ini" in text
    assert "novacommerce.api.runtime:create_runtime_app" in text
    seed_start = text.index("  commerce-seed:")
    seed_block = text[seed_start : text.index("\nsecrets:", seed_start)]
    assert 'profiles: ["seed"]' in seed_block
    assert "target: seed" in seed_block
    assert "commerce-migrate:" in seed_block


def test_compose_does_not_publish_commerce_database_port_or_add_later_infrastructure() -> None:
    text = compose_text()
    commerce_block = text[text.index("  commerce-postgres:") : text.index("  commerce-migrate:")]
    assert "ports:" not in commerce_block
    assert "redis" not in commerce_block.lower()
    assert "rabbit" not in text.lower()
    assert "kafka" not in text.lower()


def test_build_and_quality_configuration_includes_both_packages() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '"src/novacommerce"' in pyproject
    assert 'source = ["verbaops", "novacommerce"]' in pyproject
    assert "commerce_migrations" in dockerfile
    assert "alembic-commerce.ini" in dockerfile
    assert "--cov=novacommerce" in workflow
