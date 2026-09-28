from pytest import approx

from verbaops.retrieval.profile import PRODUCTION_RETRIEVAL_PROFILE


def test_production_retrieval_profile_matches_frozen_m5c_selection() -> None:
    profile = PRODUCTION_RETRIEVAL_PROFILE

    assert profile.version == "knowledge-retrieval-v1.1"
    assert profile.strategy == "hybrid_rrf"
    assert profile.dense_limit == 20
    assert profile.lexical_limit == 20
    assert profile.rrf_k == 60
    assert profile.fused_limit == 20
    assert profile.rerank_limit == 20
    assert profile.final_limit == 5
    assert profile.threshold == approx(0.032018442622950824)
    assert profile.embedding_profile == "multilingual-e5-base-v1"
    assert profile.embedding_model == "intfloat/multilingual-e5-base"
    assert profile.reranker_model is None
