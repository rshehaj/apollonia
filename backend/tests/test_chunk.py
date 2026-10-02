import pytest

from apollonia.ingest.chunk import (
    ChunkDraft,
    ChunkingConfig,
    chunk_section,
    chunk_sections,
    split_sentences,
)
from apollonia.ingest.clean import Section


def words(text: str) -> int:
    return len(text.split())


def test_split_sentences_on_terminal_punctuation_and_newlines() -> None:
    assert split_sentences("Një. Dy? Tre!\nKatër") == ["Një.", "Dy?", "Tre!", "Katër"]


def test_short_section_becomes_one_chunk() -> None:
    section = Section(("Teuta", "Lufta"), "Teuta luftoi. Roma fitoi.")
    assert chunk_section(section, words, ChunkingConfig(10, 15, 3)) == [
        ChunkDraft("Teuta > Lufta", "Teuta luftoi. Roma fitoi.")
    ]


def test_long_section_is_packed_greedily_with_sentence_overlap() -> None:
    section = Section(("T",), "a1 a2 a3. b1 b2 b3. c1 c2 c3. d1 d2 d3.")
    chunks = chunk_section(
        section, words, ChunkingConfig(target_tokens=7, max_tokens=10, overlap_tokens=3)
    )
    assert [c.text for c in chunks] == [
        "a1 a2 a3. b1 b2 b3.",
        "b1 b2 b3. c1 c2 c3.",
        "c1 c2 c3. d1 d2 d3.",
    ]


def test_oversized_sentence_is_hard_split_within_max_tokens() -> None:
    sentence = " ".join(f"w{i}" for i in range(25)) + "."
    chunks = chunk_section(Section(("T",), sentence), words, ChunkingConfig(7, 10, 3))
    assert [words(c.text) for c in chunks] == [10, 10, 5]
    assert " ".join(c.text for c in chunks) == sentence


def test_embed_text_prefixes_heading_path() -> None:
    assert ChunkDraft("A > B", "Tekst.").embed_text == "A > B\nTekst."


def test_chunk_sections_preserves_order() -> None:
    sections = [Section(("T",), "Hyrje."), Section(("T", "S"), "Seksion.")]
    assert [c.section_path for c in chunk_sections(sections, words, ChunkingConfig())] == [
        "T",
        "T > S",
    ]


@pytest.mark.parametrize(("target", "maximum", "overlap"), [(0, 10, 0), (11, 10, 0), (10, 10, 10)])
def test_invalid_chunking_config_is_rejected(target: int, maximum: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(target, maximum, overlap)
