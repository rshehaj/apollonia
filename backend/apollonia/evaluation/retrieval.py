"""Retrieval evaluation: does the right passage appear near the top?"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apollonia.config import BACKEND_DIR
from apollonia.db.models import Chunk, Document
from apollonia.embeddings import Embedder
from apollonia.ingest.chunk import ChunkingConfig
from apollonia.ingest.clean import PATH_SEPARATOR
from apollonia.normalize import fold_key
from apollonia.retrieval.search import SearchMode, search

RETRIEVAL_DATASET = BACKEND_DIR / "evals" / "data" / "retrieval.yaml"
MODES = (SearchMode.VECTOR, SearchMode.KEYWORD, SearchMode.HYBRID)
MIN_DEPTH = 5  # the report always shows Recall@5


class ExpectedSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    section: str | None = None

    def matches(self, title: str, section_path: str) -> bool:
        if title != self.title:
            return False
        if self.section is None:
            return True
        # section_path is "Title > Section > ...": the title prefix must not count.
        _, _, sections = section_path.partition(PATH_SEPARATOR)
        return fold_key(self.section) in fold_key(sections)


class RetrievalCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected: tuple[ExpectedSource, ...] = Field(min_length=1)


def load_retrieval_cases(path: Path) -> list[RetrievalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of cases")
    if not raw:
        raise ValueError(f"{path}: no cases")
    cases = [RetrievalCase.model_validate(item) for item in raw]
    duplicates = sorted(cid for cid, n in Counter(c.id for c in cases).items() if n > 1)
    if duplicates:
        raise ValueError(f"{path}: duplicate case ids: {', '.join(duplicates)}")
    return cases


def first_relevant_rank(
    results: Sequence[tuple[str, str]], expected: Sequence[ExpectedSource]
) -> int | None:
    """1-based rank of the first (title, section_path) result matching any expectation."""
    for rank, (title, section_path) in enumerate(results, start=1):
        if any(e.matches(title, section_path) for e in expected):
            return rank
    return None


def recall_at_k(ranks: Sequence[int | None], k: int) -> float:
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mrr_at_k(ranks: Sequence[int | None], k: int) -> float:
    if not ranks:
        return 0.0
    return sum(1 / r for r in ranks if r is not None and r <= k) / len(ranks)


@dataclass(frozen=True)
class ModeResult:
    mode: SearchMode
    ranks: dict[str, int | None]

    def recall(self, k: int) -> float:
        return recall_at_k(list(self.ranks.values()), k)

    def mrr(self, k: int) -> float:
        return mrr_at_k(list(self.ranks.values()), k)


@dataclass(frozen=True)
class RetrievalReport:
    generated_at: datetime
    dataset: str
    embedding_model: str
    document_count: int
    chunk_count: int
    depth: int
    cases: tuple[RetrievalCase, ...]
    results: tuple[ModeResult, ...]
    missing_labels: tuple[str, ...] = ()
    dataset_sha256: str | None = None
    chunking: ChunkingConfig | None = None
    search_candidates: int | None = None
    apollonia_version: str | None = None

    def result_for(self, mode: SearchMode) -> ModeResult:
        return next(r for r in self.results if r.mode is mode)


def run_retrieval_eval(
    session: Session,
    embedder: Embedder,
    cases: Sequence[RetrievalCase],
    *,
    depth: int = 10,
    candidates: int = 20,
    embedding_model: str,
    dataset_name: str,
    now: datetime | None = None,
    dataset_sha256: str | None = None,
    chunking: ChunkingConfig | None = None,
    apollonia_version: str | None = None,
) -> RetrievalReport:
    if depth < MIN_DEPTH:
        raise ValueError(f"depth must be at least {MIN_DEPTH} (the report shows Recall@5)")
    # search() needs at least `depth` candidates per list to return `depth` results.
    effective_candidates = max(candidates, depth)
    results = []
    for mode in MODES:
        ranks: dict[str, int | None] = {}
        for case in cases:
            hits = search(
                session,
                embedder,
                case.question,
                k=depth,
                candidates=effective_candidates,
                mode=mode,
            )
            ranks[case.id] = first_relevant_rank(
                [(h.document_title, h.section_path) for h in hits], case.expected
            )
        results.append(ModeResult(mode=mode, ranks=ranks))

    expected_titles = {e.title for case in cases for e in case.expected}
    corpus_titles = set(
        session.scalars(select(Document.title).where(Document.title.in_(expected_titles)))
    )

    return RetrievalReport(
        generated_at=now or datetime.now(UTC),
        dataset=dataset_name,
        embedding_model=embedding_model,
        document_count=session.scalar(select(func.count()).select_from(Document)) or 0,
        chunk_count=session.scalar(select(func.count()).select_from(Chunk)) or 0,
        depth=depth,
        cases=tuple(cases),
        results=tuple(results),
        missing_labels=tuple(sorted(expected_titles - corpus_titles)),
        dataset_sha256=dataset_sha256,
        chunking=chunking,
        search_candidates=effective_candidates,
        apollonia_version=apollonia_version,
    )


def render_markdown(report: RetrievalReport) -> str:
    dataset = f"`{report.dataset}` ({len(report.cases)} questions)"
    if report.dataset_sha256:
        dataset += f", sha256 `{report.dataset_sha256}`"
    lines = [
        f"# Retrieval evaluation — {report.generated_at.date().isoformat()}",
        "",
        "| Setting | Value |",
        "|---|---|",
        f"| Dataset | {dataset} |",
        f"| Corpus | {report.document_count} documents, {report.chunk_count} chunks |",
        f"| Embedding model | `{report.embedding_model}` |",
        f"| Search depth | top {report.depth} |",
    ]
    if report.search_candidates is not None:
        lines.append(f"| Search candidates | {report.search_candidates} |")
    if report.chunking is not None:
        c = report.chunking
        lines.append(
            f"| Chunking | target {c.target_tokens}, max {c.max_tokens}, "
            f"overlap {c.overlap_tokens} tokens |"
        )
    if report.apollonia_version:
        lines.append(f"| Apollonia version | `{report.apollonia_version}` |")
    lines += [
        "",
        "## Results",
        "",
        f"| Mode | Recall@1 | Recall@5 | MRR@{report.depth} |",
        "|---|---|---|---|",
    ]
    for result in report.results:
        lines.append(
            f"| {result.mode.value} | {result.recall(1):.2f} | {result.recall(5):.2f} "
            f"| {result.mrr(report.depth):.2f} |"
        )
    lines += [
        "",
        "_Development set: the same questions are used for tuning, "
        "so these numbers are optimistic._",
    ]

    if report.results:
        modes = {r.mode for r in report.results}
        shown = (
            report.result_for(SearchMode.HYBRID)
            if SearchMode.HYBRID in modes
            else report.results[-1]
        )
        misses = [c for c in report.cases if shown.ranks.get(c.id) is None]
        lines += ["", f"## Misses ({shown.mode.value}, not in top {report.depth})", ""]
        lines += [f"- `{c.id}` {c.question}" for c in misses] or ["None."]

    if report.missing_labels:
        lines += [
            "",
            "## Labels not in corpus",
            "",
            "These expected titles are not in the knowledge base; "
            "cases labeled only with them can't be hits.",
            "",
        ]
        lines += [f"- {title}" for title in report.missing_labels]
    return "\n".join(lines) + "\n"
