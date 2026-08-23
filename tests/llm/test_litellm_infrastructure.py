from pathlib import Path

ROOT = Path(__file__).parents[2]
NORMAL_CONFIG = ROOT / "infra" / "litellm" / "config.yaml"
TEST_CONFIG = ROOT / "infra" / "litellm" / "config.test.yaml"
COMPOSE = ROOT / "docker-compose.llm-gateway.yml"
PROVIDER = ROOT / "scripts" / "llm_test_provider.py"


def test_normal_litellm_config_declares_all_capability_aliases_and_env_provider_values() -> None:
    text = NORMAL_CONFIG.read_text(encoding="utf-8")

    for alias in ("agent-fast", "agent-reasoning", "eval-judge", "embedding-multilingual"):
        assert f"model_name: {alias}" in text
    assert "os.environ/VERBAOPS_AGENT_FAST_MODEL" in text
    assert "os.environ/VERBAOPS_AGENT_FAST_BASE_URL" in text
    assert "os.environ/VERBAOPS_AGENT_FAST_API_KEY" in text
    assert "os.environ/LITELLM_MASTER_KEY" in text


def test_test_config_routes_agent_fast_to_local_provider_without_external_credentials() -> None:
    text = TEST_CONFIG.read_text(encoding="utf-8")

    assert "model_name: agent-fast" in text
    assert "http://provider-stub:8000/v1" in text
    assert "local-test-provider-key" in text
    assert "os.environ" not in text
    assert "api.openai.com" not in text
    assert "anthropic.com" not in text


def test_compose_pins_stable_litellm_image_and_contains_only_local_gateway_services() -> None:
    text = COMPOSE.read_text(encoding="utf-8")

    assert (
        "ghcr.io/berriai/litellm:v1.98.0@sha256:20b5044b619055374061a6d5b7b08754cad75aeabbf82ddf4f69cc0cf80ddaf4"
        in text
    )
    assert "latest" not in text.lower()
    assert "-rc" not in text.lower()
    assert "provider-stub:" in text
    assert "llm-gateway:" in text
    assert "config.test.yaml" in text
    assert "healthcheck:" in text
    assert "depends_on:" in text


def test_provider_stub_implements_local_openai_compatible_surface() -> None:
    text = PROVIDER.read_text(encoding="utf-8")

    for marker in ("/health", "/v1/models", "/v1/chat/completions"):
        assert marker in text
    for marker in ("tool_calls", "prompt_tokens", "completion_tokens"):
        assert marker in text
