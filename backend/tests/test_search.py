import math
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from apollonia.db.models import Chunk, Document
from apollonia.embeddings import EMBEDDING_DIM, FakeEmbedder
from apollonia.retrieval.search import SearchMode, keyword_search, search, vector_search

pytestmark = pytest.mark.integration


def test_hybrid_search_finds_the_relevant_chunk(
    seeded_session: Session, embedder: FakeEmbedder
) -> None:
    results = search(seeded_session, embedder, "Kush e mbrojti Krujën nga ushtria osmane?", k=3)

    assert len(results) == 3
    top = results[0]
    assert top.document_title == "Skënderbeu"
    assert top.section_path == "Skënderbeu > Rrethimi i Krujës"
    assert top.permalink == "https://sq.wikipedia.org/w/index.php?title=Sk%C3%ABnderbeu&oldid=102"
    assert top.vector_similarity is not None
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)


def test_keyword_search_ignores_accents(seeded_session: Session, embedder: FakeEmbedder) -> None:
    results = search(seeded_session, embedder, "Skenderbeu Krujen", mode=SearchMode.KEYWORD)

    assert results[0].section_path == "Skënderbeu > Rrethimi i Krujës"
    assert all(r.vector_similarity is None for r in results)


def test_natural_language_question_matches_keywords_despite_stopwords(
    seeded_session: Session, embedder: FakeEmbedder
) -> None:
    results = search(
        seeded_session, embedder, "Kur u themelua Lidhja e Prizrenit?", mode=SearchMode.KEYWORD
    )
    assert results
    assert results[0].document_title == "Lidhja e Prizrenit"


def test_stopword_only_query_falls_back_to_vector_results(
    seeded_session: Session, embedder: FakeEmbedder
) -> None:
    # "Kur" and "ishte" are stop words, so keyword search contributes nothing.
    assert keyword_search(seeded_session, "Kur ishte?", 20) == []
    assert len(search(seeded_session, embedder, "Kur ishte?", k=2)) == 2


def test_k_larger_than_candidates_is_honoured(
    seeded_session: Session, embedder: FakeEmbedder
) -> None:
    results = search(seeded_session, embedder, "Prizren", k=5, candidates=2, mode=SearchMode.VECTOR)
    assert len(results) == 5


def test_k_limits_results(seeded_session: Session, embedder: FakeEmbedder) -> None:
    assert len(search(seeded_session, embedder, "Prizren", k=1)) == 1


def test_blank_query_is_rejected(seeded_session: Session, embedder: FakeEmbedder) -> None:
    with pytest.raises(ValueError, match="empty"):
        search(seeded_session, embedder, "   ")


def test_vector_search_skips_chunks_without_a_finite_similarity(
    seeded_session: Session, embedder: FakeEmbedder
) -> None:
    # A zero vector has no direction: pgvector returns NaN for its cosine distance, and a
    # NaN score would break JSON serialization in the API.
    broken = Chunk(
        ordinal=0,
        section_path="Bosh",
        text="Bosh",
        embedding=[0.0] * EMBEDDING_DIM,
        content_hash="0" * 64,
    )
    seeded_session.add(
        Document(
            title="Bosh",
            url="https://sq.wikipedia.org/wiki/Bosh",
            revision_id=1,
            content_hash="0" * 64,
            fetched_at=datetime.now(UTC),
            chunks=[broken],
        )
    )
    seeded_session.commit()

    hits = vector_search(seeded_session, embedder.embed_query("Prizren"), limit=20)
    assert len(hits) == 5
    assert broken.id not in {chunk_id for chunk_id, _ in hits}
    assert all(math.isfinite(similarity) for _, similarity in hits)

    results = search(seeded_session, embedder, "Prizren", k=10, mode=SearchMode.VECTOR)
    assert broken.id not in {r.chunk_id for r in results}
