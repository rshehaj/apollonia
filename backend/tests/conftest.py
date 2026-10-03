from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from apollonia.db.migrate import upgrade
from apollonia.db.session import make_engine
from apollonia.embeddings import FakeEmbedder
from apollonia.ingest.chunk import ChunkingConfig
from apollonia.ingest.pipeline import ingest_article
from tests.support import SAMPLE_ARTICLES, SAMPLE_TOPICS


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as container:
        url: str = container.get_connection_url()
        upgrade(url)
        yield url


_TRUNCATE = text("TRUNCATE document_topics, chunks, documents RESTART IDENTITY CASCADE")


@pytest.fixture
def session(database_url: str) -> Iterator[Session]:
    engine = make_engine(database_url)
    try:
        # Truncate at setup too, so a test starts clean even if earlier code wrote
        # through its own engine.
        with engine.begin() as connection:
            connection.execute(_TRUNCATE)
        with Session(engine) as db_session:
            yield db_session
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(_TRUNCATE)
        finally:
            engine.dispose()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def chunking() -> ChunkingConfig:
    return ChunkingConfig(target_tokens=60, max_tokens=80, overlap_tokens=10)


@pytest.fixture
def seeded_session(session: Session, embedder: FakeEmbedder, chunking: ChunkingConfig) -> Session:
    for article in SAMPLE_ARTICLES:
        ingest_article(session, article, SAMPLE_TOPICS[article.title], embedder, chunking)
    return session
