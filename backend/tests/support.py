"""Shared test data and doubles."""

from collections.abc import Mapping

from apollonia.ingest.wikipedia import Article

SAMPLE_ARTICLES: tuple[Article, ...] = (
    Article(
        title="Lidhja e Prizrenit",
        revision_id=101,
        url="https://sq.wikipedia.org/wiki/Lidhja_e_Prizrenit",
        text=(
            "Lidhja e Prizrenit ishte një organizatë politike shqiptare e themeluar "
            "më 10 qershor 1878 në Prizren.\n\n"
            "== Kongresi i Berlinit ==\n"
            "Lidhja i dërgoi një memorandum Kongresit të Berlinit "
            "për të mbrojtur tokat shqiptare.\n\n"
            "== Referime ==\n1. Burim."
        ),
    ),
    Article(
        title="Skënderbeu",
        revision_id=102,
        url="https://sq.wikipedia.org/wiki/Sk%C3%ABnderbeu",
        text=(
            "Gjergj Kastrioti Skënderbeu ishte heroi kombëtar i shqiptarëve.\n\n"
            "== Rrethimi i Krujës ==\n"
            "Skënderbeu mbrojti Krujën nga ushtria osmane më 1450."
        ),
    ),
    Article(
        title="Kongresi i Manastirit",
        revision_id=103,
        url="https://sq.wikipedia.org/wiki/Kongresi_i_Manastirit",
        text="Kongresi i Manastirit u mbajt në nëntor 1908 dhe miratoi alfabetin e gjuhës shqipe.",
    ),
)

SAMPLE_TOPICS: dict[str, list[str]] = {
    "Lidhja e Prizrenit": ["rilindja"],
    "Skënderbeu": ["skenderbeu"],
    "Kongresi i Manastirit": ["rilindja"],
}


class FakeArticleSource:
    """In-memory stand-in for ``WikipediaClient``: values may be articles, None or errors."""

    def __init__(self, articles: Mapping[str, Article | Exception | None]) -> None:
        self._articles = dict(articles)
        self.requests: list[tuple[str, bool]] = []

    def fetch_article(self, title: str, *, refresh: bool = False) -> Article | None:
        self.requests.append((title, refresh))
        value = self._articles.get(title)
        if isinstance(value, Exception):
            raise value
        return value
