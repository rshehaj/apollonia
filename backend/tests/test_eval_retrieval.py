from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from apollonia.config import DEFAULT_TOPICS_PATH
from apollonia.embeddings import FakeEmbedder
from apollonia.evaluation.retrieval import (
    RETRIEVAL_DATASET,
    ExpectedSource,
    ModeResult,
    RetrievalCase,
    RetrievalReport,
    first_relevant_rank,
    load_retrieval_cases,
    mrr_at_k,
    recall_at_k,
    render_markdown,
    run_retrieval_eval,
)
from apollonia.ingest.chunk import ChunkingConfig
from apollonia.retrieval.search import SearchMode
from apollonia.topics import load_topics, topic_ids_by_title


def test_first_relevant_rank_matches_title_and_optional_section() -> None:
    results = [
        ("Skënderbeu", "Skënderbeu"),
        ("Lidhja e Prizrenit", "Lidhja e Prizrenit > Kongresi i Berlinit"),
    ]
    assert first_relevant_rank(results, [ExpectedSource(title="Lidhja e Prizrenit")]) == 2
    assert (
        first_relevant_rank(
            results, [ExpectedSource(title="Lidhja e Prizrenit", section="kongresi i berlinit")]
        )
        == 2
    )
    assert (
        first_relevant_rank(
            results, [ExpectedSource(title="Lidhja e Prizrenit", section="Referime")]
        )
        is None
    )


def test_section_label_ignores_the_title_prefix() -> None:
    results = [
        ("Lidhja e Prizrenit", "Lidhja e Prizrenit"),
        ("Lidhja e Prizrenit", "Lidhja e Prizrenit > Kongresi i Berlinit"),
    ]
    assert (
        first_relevant_rank(results, [ExpectedSource(title="Lidhja e Prizrenit", section="Lidhja")])
        is None
    )
    assert (
        first_relevant_rank(
            results, [ExpectedSource(title="Lidhja e Prizrenit", section="Berlinit")]
        )
        == 2
    )


def test_recall_and_mrr() -> None:
    ranks = [1, 3, None, 6]
    assert recall_at_k(ranks, 1) == 0.25
    assert recall_at_k(ranks, 5) == 0.5
    assert mrr_at_k(ranks, 10) == pytest.approx((1 + 1 / 3 + 0 + 1 / 6) / 4)
    assert recall_at_k([], 5) == 0.0
    assert mrr_at_k([], 5) == 0.0


def test_bundled_dataset_is_valid_and_labels_known_articles() -> None:
    cases = load_retrieval_cases(RETRIEVAL_DATASET)
    known_titles = set(topic_ids_by_title(load_topics(DEFAULT_TOPICS_PATH)))

    assert len(cases) >= 50
    assert {e.title for c in cases for e in c.expected} <= known_titles


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- {id: q1, question: 'A?', expected: [{title: X}]}\n"
        "- {id: q1, question: 'B?', expected: [{title: Y}]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate case ids: q1"):
        load_retrieval_cases(path)


def test_empty_case_list_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no cases"):
        load_retrieval_cases(path)


def test_run_retrieval_eval_rejects_depth_below_5() -> None:
    case = RetrievalCase(id="q1", question="A?", expected=(ExpectedSource(title="X"),))
    with pytest.raises(ValueError, match="depth"):
        run_retrieval_eval(
            None,  # type: ignore[arg-type]  # validation happens before any query
            FakeEmbedder(),
            [case],
            depth=4,
            embedding_model="fake",
            dataset_name="test.yaml",
        )


@pytest.mark.integration
def test_run_retrieval_eval_scores_each_mode(
    seeded_session: Session, embedder: FakeEmbedder
) -> None:
    cases = [
        RetrievalCase(
            id="q1",
            question="Kush e mbrojti Krujën nga ushtria osmane?",
            expected=(ExpectedSource(title="Skënderbeu"),),
        ),
        RetrievalCase(
            id="q2",
            question="Kur u mbajt Kongresi i Manastirit?",
            expected=(ExpectedSource(title="Kongresi i Manastirit"),),
        ),
        RetrievalCase(
            id="q3",
            question="Çfarë është fotosinteza?",
            expected=(ExpectedSource(title="Fotosinteza"),),
        ),
    ]

    report = run_retrieval_eval(
        seeded_session,
        embedder,
        cases,
        depth=5,
        candidates=3,
        embedding_model="fake",
        dataset_name="test.yaml",
    )

    assert [r.mode for r in report.results] == [
        SearchMode.VECTOR,
        SearchMode.KEYWORD,
        SearchMode.HYBRID,
    ]
    hybrid = report.result_for(SearchMode.HYBRID)
    assert hybrid.ranks == {"q1": 1, "q2": 1, "q3": None}
    assert (report.document_count, report.chunk_count) == (3, 5)
    assert report.missing_labels == ("Fotosinteza",)
    assert report.search_candidates == 5  # the effective count: max(candidates, depth)


def test_render_markdown_contains_summary_table_and_misses() -> None:
    cases = (
        RetrievalCase(id="q1", question="A?", expected=(ExpectedSource(title="X"),)),
        RetrievalCase(id="q2", question="B?", expected=(ExpectedSource(title="Y"),)),
    )
    report = RetrievalReport(
        generated_at=datetime(2026, 10, 3, tzinfo=UTC),
        dataset="retrieval.yaml",
        embedding_model="BAAI/bge-m3",
        document_count=3,
        chunk_count=5,
        depth=10,
        cases=cases,
        results=(ModeResult(mode=SearchMode.HYBRID, ranks={"q1": 1, "q2": None}),),
        missing_labels=("Y",),
        dataset_sha256="0123456789ab",
        chunking=ChunkingConfig(target_tokens=350, max_tokens=500, overlap_tokens=50),
        search_candidates=20,
        apollonia_version="0.1.0",
    )

    markdown = render_markdown(report)

    assert "# Retrieval evaluation — 2026-10-03" in markdown
    assert "| hybrid | 0.50 | 0.50 | 0.50 |" in markdown
    assert "- `q2` B?" in markdown
    assert "sha256 `0123456789ab`" in markdown
    assert "| Chunking | target 350, max 500, overlap 50 tokens |" in markdown
    assert "| Search candidates | 20 |" in markdown
    assert "| Apollonia version | `0.1.0` |" in markdown
    assert "_Development set: the same questions are used for tuning" in markdown
    assert "## Labels not in corpus" in markdown
    assert "- Y" in markdown


def _report(results: tuple[ModeResult, ...]) -> RetrievalReport:
    return RetrievalReport(
        generated_at=datetime(2026, 10, 3, tzinfo=UTC),
        dataset="retrieval.yaml",
        embedding_model="fake",
        document_count=0,
        chunk_count=0,
        depth=10,
        cases=(RetrievalCase(id="q1", question="A?", expected=(ExpectedSource(title="X"),)),),
        results=results,
    )


def test_render_markdown_misses_use_hybrid_and_skip_when_no_results() -> None:
    markdown = render_markdown(
        _report(
            (
                ModeResult(mode=SearchMode.HYBRID, ranks={"q1": None}),
                ModeResult(mode=SearchMode.VECTOR, ranks={"q1": 1}),
            )
        )
    )
    assert "## Misses (hybrid, not in top 10)" in markdown
    assert "- `q1` A?" in markdown

    empty = render_markdown(_report(()))
    assert "## Misses" not in empty
    assert "## Labels not in corpus" not in empty
