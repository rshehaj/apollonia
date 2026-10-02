"""Text normalization shared by indexing and querying.

Students often type Albanian without diacritics ("Skenderbeu" for "Skënderbeu"), so both
documents and queries are accent-folded before keyword matching.
"""

import re
import unicodedata

_WORD = re.compile(r"[a-z0-9]+")

# Accent-folded Albanian function words that carry no search signal.
STOPWORDS = frozenset(
    {
        "a", "ai", "ajo", "apo", "asaj", "ata", "atij", "ato", "ca", "cfare", "cila", "cilat",
        "cilen", "ciles", "cilet", "cili", "cilin", "cilit", "cka", "deri", "dhe", "do", "duke",
        "e", "edhe", "eshte", "gjate", "i", "ishin", "ishte", "jane", "jo", "ka", "kane", "ke",
        "kete", "keto", "kishin", "kishte", "kjo", "ku", "kur", "kush", "ky", "mbi", "me", "midis",
        "mund", "nder", "ne", "nen", "nese", "nga", "nje", "nuk", "o", "ose", "pa", "pas", "per",
        "perse", "po", "por", "prej", "pse", "qe", "qysh", "rreth", "sa", "saj", "se", "sepse",
        "si", "sipas", "te", "tek", "tij", "tyre", "u", "une",
    }
)  # fmt: skip


def fold_accents(text: str) -> str:
    """Strip combining marks: "ë" → "e", "ç" → "c".

    Matches PostgreSQL's ``unaccent`` for letters with diacritics (all of Albanian); letters
    such as "ł" or "ß", which have no decomposition, are not converted.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def keyword_terms(query: str) -> list[str]:
    """Search terms for full-text matching: folded, lower-cased, stop words removed.

    Only ``[a-z0-9]+`` tokens survive, so the result is always safe to join into a
    PostgreSQL ``tsquery``.
    """
    words = _WORD.findall(fold_accents(query).lower())
    kept = (w for w in words if w not in STOPWORDS and (len(w) > 1 or w.isdigit()))
    return list(dict.fromkeys(kept))
