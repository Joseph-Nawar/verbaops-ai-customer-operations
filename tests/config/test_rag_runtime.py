from pathlib import Path

import pytest

from verbaops.config.settings import RAGSettings, Settings

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_rag_settings_are_nested_and_reject_url_credentials() -> None:
    settings = Settings.model_validate(
        {
            "rag": {
                "reranker_url": "http://tei-reranker:80",
                "timeout_seconds": 7,
            }
        }
    )

    assert settings.rag.reranker_url == "http://tei-reranker:80"
    assert settings.rag.timeout_seconds == 7
    with pytest.raises(ValueError) as error:
        RAGSettings(reranker_url="http://user:password@tei-reranker:80")
    assert "password" not in str(error.value)


def test_rag_compose_profile_is_pinned_and_keeps_embedding_alias() -> None:
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    rag_gateway = (REPOSITORY_ROOT / "infra/litellm/config.rag.yaml").read_text(encoding="utf-8")

    assert 'profiles: ["rag-models"]' in compose
    assert "tei-embedding:" in compose
    assert "tei-reranker:" in compose
    assert "rag-llm-gateway:" in compose
    assert (
        "ghcr.io/huggingface/text-embeddings-inference:cpu-1.9@"
        "sha256:c26a226262ad4ff3330fb30b76653c1bb65da2fcf413b92284545a010e0a8a48"
    ) in compose
    assert '"--model-id",' in compose
    assert '"intfloat/multilingual-e5-base",' in compose
    assert '"d128750597153bb5987e10b1c3493a34e5a4502a",' in compose
    assert '"cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",' in compose
    assert '"1427fd652930e4ba29e8149678df786c240d8825",' in compose
    assert "embedding-multilingual" in rag_gateway
    assert "http://tei-embedding:80/v1" in rag_gateway
    assert "local-rag-gateway-key" in compose
    assert "HF_TOKEN" not in compose
    assert "HUGGINGFACE_HUB_TOKEN" not in compose
