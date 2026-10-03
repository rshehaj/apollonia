from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from apollonia.db.migrate import upgrade
from apollonia.db.session import make_engine
from apollonia.embeddings import FakeEmbedder
from apollonia.ingest.chunk import ChunkingConfig


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as container:
        url: str = container.get_connection_url()
        upgrade(url)
        yield url


@pytest.fixture
def session(database_url: str) -> Iterator[Session]:
    engine = make_engine(database_url)
    with Session(engine) as db_session:
        yield db_session
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE document_topics, chunks, documents RESTART IDENTITY CASCADE")
        )
    engine.dispose()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def chunking() -> ChunkingConfig:
    return ChunkingConfig(target_tokens=60, max_tokens=80, overlap_tokens=10)
