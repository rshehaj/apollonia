"""Text embedding backends."""

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

from apollonia.config import Settings
from apollonia.normalize import fold_accents

EMBEDDING_DIM = 1024


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def count_tokens(self, text: str) -> int: ...


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder.

    Needs no model download, so tests and CI run anywhere. Texts that share words get
    similar vectors, which is enough to exercise ranking logic.
    """

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    @staticmethod
    def _embed(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIM
        for word in re.findall(r"\w+", fold_accents(text).lower()):
            index = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16) % EMBEDDING_DIM
            vector[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class BgeM3Embedder:
    """``BAAI/bge-m3`` dense embeddings on CPU (multilingual, 1024 dimensions)."""

    def __init__(self, model_name: str = "BAAI/bge-m3", batch_size: int = 16) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise RuntimeError(
                "The bge-m3 embedder needs the 'embeddings' extra: uv sync --extra embeddings"
            ) from exc
        self._model = SentenceTransformer(model_name, device="cpu")
        self._model.max_seq_length = 1024  # chunks are <= 512 tokens; caps memory use
        self._batch_size = batch_size

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 64,
        ).tolist()
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def count_tokens(self, text: str) -> int:
        input_ids: list[int] = self._model.tokenizer(text, add_special_tokens=False)["input_ids"]
        return len(input_ids)


def create_embedder(settings: Settings) -> Embedder:
    if settings.embedder == "fake":
        return FakeEmbedder()
    return BgeM3Embedder(settings.embedding_model)
