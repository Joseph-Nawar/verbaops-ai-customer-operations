"""Verify the isolated database has the exact genuine M5D knowledge state."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from verbaops.knowledge.repository_tables import (
    knowledge_chunks,
    knowledge_documents,
    knowledge_versions,
)

EXPECTED_MIGRATION = "0005_retrieval_grounding_v1"
EXPECTED_PROFILE = "multilingual-e5-base-v1"
TENANT_ID = "10000000-0000-0000-0000-000000000002"


async def _verify(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            migration = await connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            documents = int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(knowledge_documents)
                    .where(knowledge_documents.c.tenant_id == TENANT_ID)
                )
                or 0
            )
            versions = await connection.execute(
                sa.select(knowledge_versions.c.status, sa.func.count())
                .select_from(
                    knowledge_versions.join(
                        knowledge_documents,
                        knowledge_documents.c.id == knowledge_versions.c.document_id,
                    )
                )
                .where(knowledge_documents.c.tenant_id == TENANT_ID)
                .group_by(knowledge_versions.c.status)
            )
            version_counts = {str(status): int(count) for status, count in versions.all()}
            chunks = await connection.execute(
                sa.select(knowledge_versions.c.status, sa.func.count())
                .select_from(
                    knowledge_chunks.join(
                        knowledge_versions,
                        knowledge_versions.c.id == knowledge_chunks.c.version_id,
                    )
                )
                .where(knowledge_chunks.c.tenant_id == TENANT_ID)
                .group_by(knowledge_versions.c.status)
            )
            chunk_counts = {str(status): int(count) for status, count in chunks.all()}
            profile_rows = await connection.execute(
                sa.select(knowledge_versions.c.embedding_profile)
                .select_from(
                    knowledge_versions.join(
                        knowledge_documents,
                        knowledge_documents.c.id == knowledge_versions.c.document_id,
                    )
                )
                .distinct()
                .where(knowledge_documents.c.tenant_id == TENANT_ID)
            )
            profiles = sorted(str(row[0]) for row in profile_rows.all())
            dimensions = await connection.execute(
                sa.select(sa.func.vector_dims(knowledge_chunks.c.embedding).label("dimension"))
                .where(knowledge_chunks.c.tenant_id == TENANT_ID)
                .distinct()
            )
            embedding_dimensions = sorted(int(row[0]) for row in dimensions.all())
            embedding_count = int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(knowledge_chunks)
                    .where(
                        knowledge_chunks.c.tenant_id == TENANT_ID,
                        knowledge_chunks.c.embedding.is_not(None),
                    )
                )
                or 0
            )
        result = {
            "migration": migration,
            "documents": documents,
            "versions": sum(version_counts.values()),
            "version_status_counts": version_counts,
            "chunks": sum(chunk_counts.values()),
            "chunk_status_counts": chunk_counts,
            "embedding_profiles": profiles,
            "embedding_dimensions": embedding_dimensions,
            "embedded_chunk_count": embedding_count,
        }
        expected = {
            "migration": EXPECTED_MIGRATION,
            "documents": 15,
            "versions": 17,
            "version_status_counts": {"active": 15, "superseded": 2},
            "chunks": 55,
            "chunk_status_counts": {"active": 51, "superseded": 4},
            "embedding_profiles": [EXPECTED_PROFILE],
            "embedding_dimensions": [768],
            "embedded_chunk_count": 55,
        }
        if any(result[key] != value for key, value in expected.items()):
            raise ValueError(
                "isolated evaluation database does not match the required corpus state"
            )
        return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("VERBAOPS_DATABASE__URL"))
    args = parser.parse_args()
    database_url = args.database_url
    if not database_url:
        root = Path(__file__).resolve().parents[1]
        env_values = {
            key: value
            for line in (root / "artifacts/m5d/stack/local.env")
            .read_text(encoding="utf-8")
            .splitlines()
            if line and "=" in line
            for key, value in [line.split("=", 1)]
        }
        state = json.loads((root / "artifacts/m5d/stack/stack.json").read_text(encoding="utf-8"))
        database_url = (
            f"postgresql+asyncpg://{env_values['VERBAOPS_DB_USER']}:{env_values['VERBAOPS_DB_PASSWORD']}"
            f"@127.0.0.1:{state['database_port']}/{env_values['VERBAOPS_DB_NAME']}"
        )
    print(json.dumps(asyncio.run(_verify(database_url)), sort_keys=True))


if __name__ == "__main__":
    main()
