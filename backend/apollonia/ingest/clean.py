"""Split a plain-text Wikipedia extract into clean, titled sections."""

import re
import unicodedata
from dataclasses import dataclass

from apollonia.normalize import fold_accents

PATH_SEPARATOR = " > "

# Reference/navigation sections carry no tutoring content. Compared accent- and case-folded.
EXCLUDED_SECTIONS = frozenset(
    fold_accents(name).casefold()
    for name in (
        "Referime", "Referimet", "Shënime", "Shih edhe", "Shiko edhe", "Lidhje të jashtme",
        "Lidhjet e jashtme", "Bibliografia", "Bibliografi", "Literatura", "Burime", "Burimet",
        "Galeria", "Shënimet", "Referenca", "Referencat", "Lexime të mëtejshme",
    )
)  # fmt: skip

# Horizontal whitespace only, so a heading cannot span lines; tolerates CRLF line endings.
_HEADING = re.compile(r"^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*\r?$", re.MULTILINE)
# Short numeric or lower-case letter markers only: "[A]" (chemistry) and "[1878]" (years) stay.
_CITATION = re.compile(r"\[(?:\d{1,3}|[a-z]|(?i:nevojitet citimi|citation needed))\]")
# Any whitespace except newlines (NBSP, thin space, narrow NBSP, tabs, ...).
_SPACES = re.compile(r"[^\S\n]+")


@dataclass(frozen=True)
class Section:
    path: tuple[str, ...]  # (article title, heading, subheading, ...)
    text: str

    @property
    def heading_path(self) -> str:
        return PATH_SEPARATOR.join(self.path)


def clean_text(text: str) -> str:
    text = _CITATION.sub("", text)
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def parse_sections(title: str, extract: str) -> list[Section]:
    """Sections in document order; excluded sections and their subsections are dropped."""
    text = unicodedata.normalize("NFC", extract)
    sections: list[Section] = []
    headings: list[str] = []
    path: tuple[str, ...] = (title,)
    skip_level: int | None = None
    pos = 0

    for match in _HEADING.finditer(text):
        _append(sections, path, text[pos : match.start()], skipping=skip_level is not None)
        level = len(match.group(1)) - 1  # "==" is level 1
        heading = _SPACES.sub(" ", match.group(2)).strip()
        if skip_level is not None and level <= skip_level:
            skip_level = None
        if skip_level is None and fold_accents(heading).casefold() in EXCLUDED_SECTIONS:
            skip_level = level
        headings = [*headings[: level - 1], heading]
        path = (title, *headings)
        pos = match.end()

    _append(sections, path, text[pos:], skipping=skip_level is not None)
    return sections


def _append(sections: list[Section], path: tuple[str, ...], body: str, *, skipping: bool) -> None:
    if skipping:
        return
    cleaned = clean_text(body)
    if cleaned:
        sections.append(Section(path, cleaned))
