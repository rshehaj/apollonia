"""Turn Wikipedia articles into stored, embedded chunks."""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from apollonia.db.models import Chunk, Document, DocumentTopic
from apollonia.embeddings import Embedder
from apollonia.ingest.chunk import ChunkingConfig, chunk_sections
from apollonia.ingest.clean import parse_sections
from apollonia.ingest.wikipedia import Article, WikipediaError
from apollonia.topics import Topic, topic_ids_by_title


class IngestStatus(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class IngestOutcome:
    title: str
    status: IngestStatus
    chunk_count: int


@dataclass
class IngestReport:
    outcomes: list[IngestOutcome] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    pruned: list[str] = field(default_factory=list)

    def summary(self) -> str:
        counts = {status: 0 for status in IngestStatus}
        for outcome in self.outcomes:
            counts[outcome.status] += 1
        parts = [
            f"Ingested {len(self.outcomes)} articles: "
            + ", ".join(f"{counts[s]} {s.value}" for s in IngestStatus)
            + "."
        ]
        if self.missing:
            parts.append(f"Missing: {', '.join(self.missing)}.")
        if self.failed:
            parts.append(f"Failed: {', '.join(self.failed)}.")
        if self.pruned:
            parts.append(f"Pruned: {', '.join(self.pruned)}.")
        return " ".join(parts)


class ArticleSource(Protocol):
    def fetch_article(self, title: str, *, refresh: bool = False) -> Article | None: ...


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_article(
    session: Session,
    article: Article,
    topic_ids: Sequence[str],
    embedder: Embedder,
    chunking: ChunkingConfig,
    *,
    now: datetime | None = None,
) -> IngestOutcome:
    """Store ``article``; re-embed only when its revision or processed content changed."""
    drafts = chunk_sections(
        parse_sections(article.title, article.text), embedder.count_tokens, chunking
    )
    doc_hash = content_hash("\n\n".join(d.embed_text for d in drafts))
    wanted_topics = list(dict.fromkeys(topic_ids))

    document = session.scalar(select(Document).where(Document.title == article.title))
    if (
        document is not None
        and document.revision_id == article.revision_id
        and document.content_hash == doc_hash
    ):
        _replace_topics(session, document, wanted_topics)
        session.commit()
        return IngestOutcome(article.title, IngestStatus.UNCHANGED, len(document.chunks))

    vectors = embedder.embed_documents([d.embed_text for d in drafts]) if drafts else []
    fetched_at = now or datetime.now(UTC)
    if document is None:
        status = IngestStatus.CREATED
        document = Document(
            title=article.title,
            url=article.url,
            revision_id=article.revision_id,
            content_hash=doc_hash,
            fetched_at=fetched_at,
        )
        session.add(document)
    else:
        status = IngestStatus.UPDATED
        # Delete old chunks first: the unit of work would otherwise insert the new rows
        # before deleting the old ones and violate UNIQUE (document_id, ordinal).
        document.chunks.clear()
        session.flush()
        document.url = article.url
        document.revision_id = article.revision_id
        document.content_hash = doc_hash
        document.fetched_at = fetched_at

    document.chunks.extend(
        Chunk(
            ordinal=ordinal,
            section_path=draft.section_path,
            text=draft.text,
            embedding=vector,
            content_hash=content_hash(draft.embed_text),
        )
        for ordinal, (draft, vector) in enumerate(zip(drafts, vectors, strict=True))
    )
    _replace_topics(session, document, wanted_topics)
    session.commit()
    return IngestOutcome(article.title, status, len(drafts))


def run_ingest(
    session: Session,
    source: ArticleSource,
    topics: Sequence[Topic],
    embedder: Embedder,
    chunking: ChunkingConfig,
    *,
    refresh: bool = False,
    prune: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> IngestReport:
    """Fetch and store every article in ``topics``; one failure never aborts the run."""
    progress = on_progress or (lambda _message: None)
    report = IngestReport()
    articles: dict[str, Article] = {}
    topics_by_canonical: dict[str, list[str]] = {}

    for title, ids in topic_ids_by_title(topics).items():
        try:
            article = source.fetch_article(title, refresh=refresh)
        except WikipediaError as exc:
            report.failed[title] = str(exc)
            progress(f"   failed  {title}: {exc}")
            continue
        if article is None:
            report.missing.append(title)
            progress(f"  missing  {title}")
            continue
        articles[article.title] = article
        merged = topics_by_canonical.setdefault(article.title, [])
        merged.extend(topic_id for topic_id in ids if topic_id not in merged)

    for title, article in articles.items():
        try:
            outcome = ingest_article(
                session, article, topics_by_canonical[title], embedder, chunking
            )
        except Exception as exc:
            session.rollback()
            report.failed[title] = f"{type(exc).__name__}: {exc}"
            progress(f"   failed  {title}: {exc}")
            continue
        report.outcomes.append(outcome)
        progress(f"{outcome.status.value:>9}  {title} ({outcome.chunk_count} chunks)")

    if prune and articles and not report.failed:
        report.pruned = _prune(session, keep=set(articles))
    return report


def _replace_topics(session: Session, document: Document, wanted: list[str]) -> None:
    if sorted(t.topic_id for t in document.topics) == sorted(wanted):
        return
    document.topics.clear()
    session.flush()
    document.topics.extend(DocumentTopic(topic_id=topic_id) for topic_id in wanted)


def _prune(session: Session, keep: set[str]) -> list[str]:
    stale = session.scalars(select(Document).where(Document.title.not_in(keep))).all()
    titles = sorted(document.title for document in stale)
    for document in stale:
        session.delete(document)
    session.commit()
    return titles
