import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.asyncio
async def test_retrieval_grounding_schema_contract_is_available(
    postgres_engine: AsyncEngine,
) -> None:
    async with postgres_engine.connect() as connection:
        tables = {
            row[0]
            for row in (
                await connection.execute(
                    text(
                        "select table_name from information_schema.tables "
                        "where table_schema='public' and table_name in "
                        "('retrieval_invocations','retrieval_candidates','message_citations')"
                    )
                )
            ).all()
        }
        assert tables == {
            "retrieval_invocations",
            "retrieval_candidates",
            "message_citations",
        }

        version_columns = {
            row[0]
            for row in (
                await connection.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_name='knowledge_versions' and column_name in "
                        "('embedding_profile','embedding_model')"
                    )
                )
            ).all()
        }
        assert version_columns == {"embedding_profile", "embedding_model"}

        constraints = {
            row[0]
            for row in (
                await connection.execute(
                    text(
                        "select constraint_name from information_schema.table_constraints "
                        "where table_schema='public' and constraint_name in "
                        "('uq_retrieval_invocations_run_sequence', "
                        "'uq_retrieval_candidates_invocation_chunk', "
                        "'uq_message_citations_message_ordinal')"
                    )
                )
            ).all()
        }
        assert constraints == {
            "uq_retrieval_invocations_run_sequence",
            "uq_retrieval_candidates_invocation_chunk",
            "uq_message_citations_message_ordinal",
        }
