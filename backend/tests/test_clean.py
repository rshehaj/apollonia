import pytest

from apollonia.ingest.clean import Section, clean_text, parse_sections

EXTRACT = """Lidhja e Prizrenit ishte një organizim politik.[1]

== Konteksti ==
Traktati i Shën Stefanit   u nënshkrua më 1878.

== Rezistenca ushtarake ==
Lidhja organizoi rezistencë.

=== Qëndrimi autonomist ===
Kërkohej autonomi.

== SHIH EDHE ==
Lidhja e Pejës

=== Nënseksion ===
Duhet hequr.

== Trashëgimia ==
Lidhja mbetet simbol.

== Lidhje te jashtme ==
https://example.org

== Bosh ==

== Referime ==
1. Burim
"""


def test_parse_sections_builds_heading_paths_and_drops_reference_sections() -> None:
    title = "Lidhja e Prizrenit"
    assert parse_sections(title, EXTRACT) == [
        Section((title,), "Lidhja e Prizrenit ishte një organizim politik."),
        Section((title, "Konteksti"), "Traktati i Shën Stefanit u nënshkrua më 1878."),
        Section((title, "Rezistenca ushtarake"), "Lidhja organizoi rezistencë."),
        Section((title, "Rezistenca ushtarake", "Qëndrimi autonomist"), "Kërkohej autonomi."),
        Section((title, "Trashëgimia"), "Lidhja mbetet simbol."),
    ]


def test_heading_path_joins_with_separator() -> None:
    section = Section(("A", "B", "C"), "x")
    assert section.heading_path == "A > B > C"


def test_article_without_headings_is_a_single_section() -> None:
    assert parse_sections("Teuta", "Teuta ishte mbretëreshë.") == [
        Section(("Teuta",), "Teuta ishte mbretëreshë.")
    ]


def test_clean_text_removes_citation_markers_and_blank_lines() -> None:
    raw = "Fjali e parë.[2]  Fjali e dytë.[nevojitet citimi]\n\n\n  Paragraf tjetër. "
    assert clean_text(raw) == "Fjali e parë. Fjali e dytë.\nParagraf tjetër."


@pytest.mark.parametrize(
    "raw",
    ["Ligji v = k[A][B].", "viti [1878] ishte"],
)
def test_clean_text_keeps_brackets_that_are_not_citations(raw: str) -> None:
    assert clean_text(raw) == raw


def test_clean_text_removes_numeric_and_letter_citations() -> None:
    assert clean_text("fjali.[12] tjetër[b]") == "fjali. tjetër"


def test_clean_text_removes_capitalised_citation_needed() -> None:
    assert clean_text("Fjali.[Nevojitet citimi]") == "Fjali."


def test_clean_text_collapses_unicode_horizontal_whitespace() -> None:
    assert clean_text("a b c d") == "a b c d"
    assert clean_text("a   b") == "a b"


def test_heading_with_irregular_whitespace_is_excluded() -> None:
    extract = "Hyrje.\n== Lidhje  të  jashtme ==\nhttps://example.org\n"
    assert parse_sections("T", extract) == [Section(("T",), "Hyrje.")]


def test_heading_does_not_span_lines() -> None:
    sections = parse_sections("T", "== A\n==\nTekst.")
    assert all(section.path[-1] != "A" for section in sections)


def test_crlf_headings_are_parsed() -> None:
    assert parse_sections("T", "== Konteksti ==\r\nTekst.\r\n") == [
        Section(("T", "Konteksti"), "Tekst.")
    ]


def test_additional_reference_sections_are_excluded() -> None:
    extract = "Hyrje.\n== Lexime të mëtejshme ==\nLibër.\n== Shënimet ==\nShënim.\n"
    assert parse_sections("T", extract) == [Section(("T",), "Hyrje.")]


@pytest.mark.parametrize(
    ("extract", "expected"),
    [
        pytest.param("", [], id="empty"),
        pytest.param("  \n\t\n ", [], id="whitespace-only"),
        pytest.param(
            "== Konteksti ==\nTekst.",
            [Section(("T", "Konteksti"), "Tekst.")],
            id="starts-with-heading",
        ),
        pytest.param(
            "== A ==\nx\n==== D ====\ny",
            [Section(("T", "A"), "x"), Section(("T", "A", "D"), "y")],
            id="level-jump",
        ),
        pytest.param(
            "== Referime ==\nr\n==== D ====\ny\n== B ==\nz",
            [Section(("T", "B"), "z")],
            id="jumped-subsection-of-excluded-section",
        ),
        pytest.param(
            "== E = mc2 ==\nFormula.",
            [Section(("T", "E = mc2"), "Formula.")],
            id="equals-sign-in-heading",
        ),
    ],
)
def test_parse_sections_edge_cases(extract: str, expected: list[Section]) -> None:
    assert parse_sections("T", extract) == expected
