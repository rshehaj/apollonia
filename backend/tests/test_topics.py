from pathlib import Path

import pytest

from apollonia.config import DEFAULT_TOPICS_PATH
from apollonia.topics import Topic, load_topics, topic_ids_by_title


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "topics.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_topics_parses_yaml(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "- id: rilindja\n  name: Rilindja Kombëtare\n  articles: [Lidhja e Prizrenit]\n",
    )
    assert load_topics(path) == [
        Topic(id="rilindja", name="Rilindja Kombëtare", articles=("Lidhja e Prizrenit",))
    ]


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "- {id: a, name: A, articles: [X]}\n- {id: a, name: B, articles: [Y]}\n",
    )
    with pytest.raises(ValueError, match="duplicate topic ids: a"):
        load_topics(path)


@pytest.mark.parametrize(
    "content",
    [
        "- {id: Not A Slug, name: A, articles: [X]}\n",
        "- {id: a, name: A, articles: []}\n",
        "id: a\n",
    ],
)
def test_invalid_topics_are_rejected(tmp_path: Path, content: str) -> None:
    with pytest.raises(ValueError):
        load_topics(_write(tmp_path, content))


def test_topic_ids_by_title_merges_topics_sharing_an_article() -> None:
    topics = [
        Topic(id="rilindja", name="R", articles=("Lidhja e Prizrenit", "Naim Frashëri")),
        Topic(id="lidhjet", name="L", articles=("Lidhja e Prizrenit",)),
    ]
    assert topic_ids_by_title(topics) == {
        "Lidhja e Prizrenit": ["rilindja", "lidhjet"],
        "Naim Frashëri": ["rilindja"],
    }


def test_bundled_topic_map_is_valid() -> None:
    topics = load_topics(DEFAULT_TOPICS_PATH)
    assert len(topics) >= 10
    assert len(topic_ids_by_title(topics)) >= 40
