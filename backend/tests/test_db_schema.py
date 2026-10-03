from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from apollonia.db.models import Chunk, Document, DocumentTopic
from apollonia.embeddings import EMBEDDING_DIM

pytestmark = pytest.mark.integration


def _document() -> Document:
    return Document(
        title="Skënderbeu",
        url="https://sq.wikipedia.org/wiki/Sk%C3%ABnderbeu",
        revision_id=1,
        content_hash="0" * 64,
        fetched_at=datetime.now(UTC),
    )


def _chunk(ordinal: int, body: str) -> Chunk:
    return Chunk(
        ordinal=ordinal,
        section_path="Skënderbeu > Rrethimi i Krujës",
        text=body,
        embedding=[1.0] + [0.0] * (EMBEDDING_DIM - 1),
        content_hash="1" * 64,
    )


def test_migration_creates_extensions_and_tables(session: Session) -> None:
    extensions = set(session.scalars(text("SELECT extname FROM pg_extension")))
    tables = set(
        session.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    )
    assert {"vector", "unaccent"} <= extensions
    assert {"documents", "chunks", "document_topics", "alembic_version"} <= tables


def test_tsv_is_accent_and_case_insensitive(session: Session) -> None:
    document = _document()
    document.chunks.append(_chunk(0, "Skënderbeu mbrojti Krujën."))
    session.add(document)
    session.commit()

    for term in ("skenderbeu", "krujen", "rrethimi"):
        matches = session.scalar(
            text("SELECT count(*) FROM chunks WHERE tsv @@ to_tsquery('simple', :term)"),
            {"term": term},
        )
        assert matches == 1, term


def test_deleting_a_document_cascades(session: Session) -> None:
    document = _document()
    document.chunks.append(_chunk(0, "Tekst."))
    document.topics.append(DocumentTopic(topic_id="skenderbeu"))
    session.add(document)
    session.commit()

    session.delete(document)
    session.commit()

    assert session.scalar(text("SELECT count(*) FROM chunks")) == 0
    assert session.scalar(text("SELECT count(*) FROM document_topics")) == 0
