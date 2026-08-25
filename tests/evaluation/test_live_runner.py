"""Tests for live-runner secret signature selection."""

from scripts.run_agent_eval_live import _secret_environment_values


def test_only_explicit_sensitive_environment_values_become_signatures() -> None:
    generated = {
        "AGENT_LIVE_API_PORT": "0",
        "AGENT_LIVE_GATEWAY_PORT": "5432",
        "VERBAOPS_AGENT_FAST_BASE_URL": "https://api.groq.com/openai/v1",
        "VERBAOPS_AGENT_FAST_MODEL": "groq/openai/gpt-oss-120b",
        "VERBAOPS_DB_PASSWORD": "synthetic-db-password",
        "LITELLM_MASTER_KEY": "synthetic-master-key",
    }
    environment = {
        "VERBAOPS_AGENT_FAST_API_KEY": "synthetic-api-key",
        "VERBAOPS_AGENT_FAST_BASE_URL": generated["VERBAOPS_AGENT_FAST_BASE_URL"],
        "VERBAOPS_AGENT_FAST_MODEL": generated["VERBAOPS_AGENT_FAST_MODEL"],
    }
    assert set(_secret_environment_values(generated, environment)) == {
        "synthetic-db-password",
        "synthetic-master-key",
        "synthetic-api-key",
    }
