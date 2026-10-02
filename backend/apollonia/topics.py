"""Matura syllabus topics and the Wikipedia articles that cover them."""

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Topic(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    articles: tuple[str, ...] = Field(min_length=1)


def load_topics(path: Path) -> list[Topic]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of topics")
    topics = [Topic.model_validate(item) for item in raw]
    duplicates = sorted(tid for tid, count in Counter(t.id for t in topics).items() if count > 1)
    if duplicates:
        raise ValueError(f"{path}: duplicate topic ids: {', '.join(duplicates)}")
    return topics


def topic_ids_by_title(topics: Sequence[Topic]) -> dict[str, list[str]]:
    """Map each article title to the ids of every topic that lists it, in file order."""
    mapping: dict[str, list[str]] = {}
    for topic in topics:
        for title in topic.articles:
            ids = mapping.setdefault(title, [])
            if topic.id not in ids:
                ids.append(topic.id)
    return mapping
