import math
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select, text
from sqlalchemy.orm import Session, defer

from apollonia.db.models import Chunk, Document
from apollonia.embeddings import Embedder
from apollonia.ingest.wikipedia import revision_permalink
from apollonia.normalize import keyword_terms
from apollonia.retrieval.fusion import reciprocal_rank_fusion

_KEYWORD_SQL = text(
    """
    SELECT id, ts_rank_cd(tsv, query) AS rank
    FROM chunks, to_tsquery('simple', :tsquery) AS query
    WHERE tsv @@ query
    ORDER BY rank DESC, id
    LIMIT :limit
    """
)


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    VECTOR = "vector"
    KEYWORD = "keyword"


@dataclass(frozen=True)
class SearchResult:
    chunk_id: int
    document_title: str
    section_path: str
    text: str
    url: str
    revision_id: int
    score: float  # RRF score (hybrid), cosine similarity (vector) or ts_rank_cd (keyword)
    vector_similarity: float | None  # None when the chunk was not a vector candidate

    @property
    def permalink(self) -> str:
        return revision_permalink(self.url, self.revision_id)


def vector_search(
    session: Session, query_vector: list[float], limit: int
) -> list[tuple[int, float]]:
    """Nearest chunks by cosine similarity, best first.

    Rows whose distance is NULL or NaN (a NULL or zero embedding) are skipped: they carry
    no similarity signal and a NaN score cannot be serialized as JSON. PostgreSQL sorts
    NULL and NaN after every number, so skipping them never drops a finite candidate.
    """
    distance = Chunk.embedding.cosine_distance(query_vector)
    rows = session.execute(select(Chunk.id, distance).order_by(distance).limit(limit)).all()
    hits = []
    for chunk_id, dist in rows:
        if dist is None or not math.isfinite(dist):
            continue
        hits.append((chunk_id, 1.0 - float(dist)))
    return hits


def keyword_search(session: Session, query: str, limit: int) -> list[tuple[int, float]]:
    terms = keyword_terms(query)
    if not terms:
        return []
    # OR the terms: an AND query would almost never match a natural-language question.
    rows = session.execute(_KEYWORD_SQL, {"tsquery": " | ".join(terms), "limit": limit}).all()
    return [(chunk_id, float(rank)) for chunk_id, rank in rows]


def search(
    session: Session,
    embedder: Embedder,
    query: str,
    *,
    k: int = 6,
    candidates: int = 20,
    mode: SearchMode = SearchMode.HYBRID,
) -> list[SearchResult]:
    query = query.strip()
    candidates = max(candidates, k)  # each retriever must supply at least k results
    if not query:
        raise ValueError("Query must not be empty")

    vector_hits = (
        vector_search(session, embedder.embed_query(query), candidates)
        if mode in (SearchMode.HYBRID, SearchMode.VECTOR)
        else []
    )
    keyword_hits = (
        keyword_search(session, query, candidates)
        if mode in (SearchMode.HYBRID, SearchMode.KEYWORD)
        else []
    )

    if mode is SearchMode.HYBRID:
        ranked = reciprocal_rank_fusion(
            [[cid for cid, _ in vector_hits], [cid for cid, _ in keyword_hits]]
        )
    else:
        ranked = vector_hits or keyword_hits
    top = ranked[:k]
    if not top:
        return []

    rows = session.execute(
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.id.in_([cid for cid, _ in top]))
        .options(defer(Chunk.embedding), defer(Chunk.tsv))
    ).all()
    by_id = {chunk.id: (chunk, document) for chunk, document in rows}
    similarities = dict(vector_hits)

    return [
        SearchResult(
            chunk_id=cid,
            document_title=by_id[cid][1].title,
            section_path=by_id[cid][0].section_path,
            text=by_id[cid][0].text,
            url=by_id[cid][1].url,
            revision_id=by_id[cid][1].revision_id,
            score=score,
            vector_similarity=similarities.get(cid),
        )
        for cid, score in top
        if cid in by_id
    ]
