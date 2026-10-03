from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from apollonia.db.models import Chunk, Document
from apollonia.embeddings import FakeEmbedder
from apollonia.ingest.chunk import ChunkingConfig
from apollonia.ingest.pipeline import IngestOutcome, IngestStatus, ingest_article, run_ingest
from apollonia.ingest.wikipedia import WikipediaError
from apollonia.topics import Topic
from tests.support import SAMPLE_ARTICLES, FakeArticleSource

pytestmark = pytest.mark.integration

LIDHJA, SKENDERBEU, _ = SAMPLE_ARTICLES


def test_ingest_article_creates_document_chunks_and_topics(
    session: Session, embedder: FakeEmbedder, chunking: ChunkingConfig
) -> None:
    outcome = ingest_article(session, LIDHJA, ["rilindja"], embedder, chunking)

    assert outcome == IngestOutcome("Lidhja e Prizrenit", IngestStatus.CREATED, 2)
    document = session.scalars(select(Document)).one()
    assert document.revision_id == 101
    assert [c.section_path for c in document.chunks] == [
        "Lidhja e Prizrenit",
        "Lidhja e Prizrenit > Kongresi i Berlinit",
    ]
    assert all("Burim" not in c.text for c in document.chunks)
    assert [t.topic_id for t in document.topics] == ["rilindja"]


def test_reingesting_an_unchanged_article_is_a_no_op(
    session: Session, embedder: FakeEmbedder, chunking: ChunkingConfig
) -> None:
    ingest_article(session, LIDHJA, ["rilindja"], embedder, chunking)
    ids_before = session.scalars(select(Chunk.id).order_by(Chunk.id)).all()

    outcome = ingest_article(session, LIDHJA, ["rilindja"], embedder, chunking)

    assert outcome.status is IngestStatus.UNCHANGED
    assert session.scalars(select(Chunk.id).order_by(Chunk.id)).all() == ids_before


def test_new_revision_replaces_chunks(
    session: Session, embedder: FakeEmbedder, chunking: ChunkingConfig
) -> None:
    ingest_article(session, LIDHJA, ["rilindja"], embedder, chunking)
    edited = replace(LIDHJA, revision_id=202, text=LIDHJA.text.replace("1878", "1879"))

    outcome = ingest_article(session, edited, ["rilindja"], embedder, chunking)

    assert outcome.status is IngestStatus.UPDATED
    session.expire_all()
    document = session.scalars(select(Document)).one()
    assert document.revision_id == 202
    assert len(document.chunks) == 2
    assert "1879" in document.chunks[0].text


def test_topic_changes_apply_without_a_new_revision(
    session: Session, embedder: FakeEmbedder, chunking: ChunkingConfig
) -> None:
    ingest_article(session, LIDHJA, ["rilindja"], embedder, chunking)

    outcome = ingest_article(session, LIDHJA, ["rilindja", "lidhjet"], embedder, chunking)

    assert outcome.status is IngestStatus.UNCHANGED
    document = session.scalars(select(Document)).one()
    assert sorted(t.topic_id for t in document.topics) == ["lidhjet", "rilindja"]


def test_run_ingest_merges_redirects_and_reports_missing_and_failed(
    session: Session, embedder: FakeEmbedder, chunking: ChunkingConfig
) -> None:
    source = FakeArticleSource(
        {
            "Lidhja e Prizrenit": LIDHJA,
            "Lidhja Shqiptare e Prizrenit": LIDHJA,  # redirect to the same article
            "Nuk ekziston": None,
            "Gabim": WikipediaError("HTTP 503"),
        }
    )
    topics = [
        Topic(id="rilindja", name="R", articles=("Lidhja e Prizrenit", "Nuk ekziston")),
        Topic(id="lidhjet", name="L", articles=("Lidhja Shqiptare e Prizrenit", "Gabim")),
    ]

    report = run_ingest(session, source, topics, embedder, chunking)

    assert [o.title for o in report.outcomes] == ["Lidhja e Prizrenit"]
    assert report.missing == ["Nuk ekziston"]
    assert report.failed == {"Gabim": "HTTP 503"}
    document = session.scalars(select(Document)).one()
    assert sorted(t.topic_id for t in document.topics) == ["lidhjet", "rilindja"]


def test_run_ingest_prunes_documents_no_longer_in_the_topic_map(
    session: Session, embedder: FakeEmbedder, chunking: ChunkingConfig
) -> None:
    ingest_article(session, SKENDERBEU, ["skenderbeu"], embedder, chunking)
    source = FakeArticleSource({"Lidhja e Prizrenit": LIDHJA})
    topics = [Topic(id="rilindja", name="R", articles=("Lidhja e Prizrenit",))]

    report = run_ingest(session, source, topics, embedder, chunking, prune=True)

    assert report.pruned == ["Skënderbeu"]
    assert session.scalars(select(Document.title)).all() == ["Lidhja e Prizrenit"]


def test_run_ingest_skips_pruning_when_a_fetch_failed(
    session: Session, embedder: FakeEmbedder, chunking: ChunkingConfig
) -> None:
    ingest_article(session, SKENDERBEU, ["skenderbeu"], embedder, chunking)
    source = FakeArticleSource({"Lidhja e Prizrenit": LIDHJA, "Gabim": WikipediaError("HTTP 503")})
    topics = [Topic(id="rilindja", name="R", articles=("Lidhja e Prizrenit", "Gabim"))]

    report = run_ingest(session, source, topics, embedder, chunking, prune=True)

    assert report.pruned == []
    assert sorted(session.scalars(select(Document.title))) == ["Lidhja e Prizrenit", "Skënderbeu"]


def test_run_ingest_forwards_refresh_and_reports_progress(
    session: Session, embedder: FakeEmbedder, chunking: ChunkingConfig
) -> None:
    source = FakeArticleSource({"Lidhja e Prizrenit": LIDHJA})
    topics = [Topic(id="rilindja", name="R", articles=("Lidhja e Prizrenit",))]
    messages: list[str] = []

    report = run_ingest(
        session, source, topics, embedder, chunking, refresh=True, on_progress=messages.append
    )

    assert source.requests == [("Lidhja e Prizrenit", True)]
    assert messages == ["  created  Lidhja e Prizrenit (2 chunks)"]
    assert report.summary() == "Ingested 1 articles: 1 created, 0 updated, 0 unchanged."
