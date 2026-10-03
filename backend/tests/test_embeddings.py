import math
from pathlib import Path

import pytest

from apollonia.config import Settings
from apollonia.embeddings import EMBEDDING_DIM, BgeM3Embedder, FakeEmbedder, create_embedder


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_fake_embedder_returns_unit_vectors_of_the_right_size() -> None:
    vector = FakeEmbedder().embed_query("Lidhja e Prizrenit")
    assert len(vector) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(dot(vector, vector)), 1.0)


def test_fake_embedder_is_deterministic_and_accent_insensitive() -> None:
    embedder = FakeEmbedder()
    assert embedder.embed_query("Skënderbeu") == embedder.embed_query("skenderbeu")


def test_fake_embedder_scores_shared_words_higher() -> None:
    embedder = FakeEmbedder()
    query = embedder.embed_query("Skënderbeu mbrojti Krujën")
    related, unrelated = embedder.embed_documents(
        ["Skënderbeu mbrojti Krujën më 1450.", "Kongresi i Manastirit miratoi alfabetin."]
    )
    assert dot(query, related) > dot(query, unrelated)


def test_fake_embedder_counts_whitespace_tokens() -> None:
    assert FakeEmbedder().count_tokens("një dy tre") == 3


def test_create_embedder_honours_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert isinstance(create_embedder(Settings(embedder="fake")), FakeEmbedder)


@pytest.mark.slow
def test_bge_m3_embeds_albanian_semantically() -> None:
    embedder = BgeM3Embedder()
    query = embedder.embed_query("Kush e udhëhoqi qëndresën kundër osmanëve?")
    related, unrelated = embedder.embed_documents(
        [
            "Skënderbeu luftoi kundër Perandorisë Osmane për 25 vjet.",
            "Fotosinteza ndodh në kloroplastet e bimëve.",
        ]
    )
    assert len(query) == EMBEDDING_DIM
    assert dot(query, related) > dot(query, unrelated)
    assert embedder.count_tokens("Lidhja e Prizrenit") > 0


def test_fake_embedder_returns_a_unit_vector_for_text_without_words() -> None:
    # A zero vector would make pgvector's cosine distance NaN.
    vector = FakeEmbedder().embed_query("?!")
    assert math.isclose(math.sqrt(dot(vector, vector)), 1.0)
