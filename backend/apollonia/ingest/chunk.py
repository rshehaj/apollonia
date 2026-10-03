"""Pack section text into overlapping, size-bounded chunks.

Chunks never cross a section boundary, and sentences are never split unless a single
sentence exceeds ``max_tokens``.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from apollonia.ingest.clean import Section

TokenCounter = Callable[[str], int]

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+|\n+")


@dataclass(frozen=True)
class ChunkingConfig:
    # The token limits apply to the chunk body only; the heading prefix that
    # ChunkDraft.embed_text adds comes on top of them (the embedder allows 1024 tokens).
    target_tokens: int = 400
    max_tokens: int = 512
    overlap_tokens: int = 50

    def __post_init__(self) -> None:
        if not 0 < self.target_tokens <= self.max_tokens:
            raise ValueError("require 0 < target_tokens <= max_tokens")
        if not 0 <= self.overlap_tokens < self.target_tokens:
            raise ValueError("require 0 <= overlap_tokens < target_tokens")


@dataclass(frozen=True)
class ChunkDraft:
    section_path: str
    text: str

    @property
    def embed_text(self) -> str:
        """What gets embedded: the heading path gives each chunk its context."""
        return f"{self.section_path}\n{self.text}"


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BOUNDARY.split(text) if s.strip()]


def chunk_sections(
    sections: Iterable[Section], count_tokens: TokenCounter, config: ChunkingConfig
) -> list[ChunkDraft]:
    return [chunk for s in sections for chunk in chunk_section(s, count_tokens, config)]


def chunk_section(
    section: Section, count_tokens: TokenCounter, config: ChunkingConfig
) -> list[ChunkDraft]:
    units = [
        (piece, count_tokens(piece))
        for sentence in split_sentences(section.text)
        for piece in _split_oversized(sentence, count_tokens, config.max_tokens)
    ]
    chunks: list[ChunkDraft] = []
    current: list[tuple[str, int]] = []
    for unit in units:
        if current and _total(current) + unit[1] > config.target_tokens:
            chunks.append(_draft(section, current))
            tail = _overlap_tail(current, config.overlap_tokens)
            # Carry a tail only if it is strictly shorter than the flushed chunk, so a
            # short chunk is never repeated whole at the start of the next one.
            current = tail if len(tail) < len(current) else []
            if _total(current) + unit[1] > config.max_tokens:
                current = []
        current.append(unit)
    if current:
        chunks.append(_draft(section, current))
    return chunks


def _split_oversized(sentence: str, count_tokens: TokenCounter, max_tokens: int) -> list[str]:
    if count_tokens(sentence) <= max_tokens:
        return [sentence]
    pieces: list[str] = []
    current: list[str] = []
    for word in sentence.split():
        if current and count_tokens(" ".join([*current, word])) > max_tokens:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _overlap_tail(units: list[tuple[str, int]], overlap_tokens: int) -> list[tuple[str, int]]:
    tail: list[tuple[str, int]] = []
    total = 0
    for unit in reversed(units):
        if total + unit[1] > overlap_tokens:
            break
        tail.insert(0, unit)
        total += unit[1]
    return tail


def _total(units: list[tuple[str, int]]) -> int:
    return sum(n for _, n in units)


def _draft(section: Section, units: list[tuple[str, int]]) -> ChunkDraft:
    return ChunkDraft(section.heading_path, " ".join(text for text, _ in units))
