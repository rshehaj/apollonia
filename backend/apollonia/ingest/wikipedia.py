"""Minimal, polite client for the MediaWiki Action API."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_S = 60.0


class WikipediaError(RuntimeError):
    """Raised when an article cannot be fetched."""


@dataclass(frozen=True)
class Article:
    title: str  # canonical title, after redirects
    revision_id: int
    text: str  # plain text; headings rendered as "== Heading =="
    url: str


def revision_permalink(article_url: str, revision_id: int) -> str:
    """Link to the exact revision an answer was based on."""
    site, _, title = article_url.partition("/wiki/")
    return f"{site}/w/index.php?title={title}&oldid={revision_id}"


class WikipediaClient:
    def __init__(
        self,
        *,
        api_url: str,
        user_agent: str,
        cache_dir: Path | None = None,
        min_interval_s: float = 1.0,
        max_attempts: int = 3,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_url = api_url
        self._site_url = api_url.removesuffix("/w/api.php")
        self._cache_dir = cache_dir
        self._min_interval_s = min_interval_s
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self._http = httpx.Client(
            headers={"User-Agent": user_agent}, timeout=timeout_s, transport=transport
        )

    def __enter__(self) -> WikipediaClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def fetch_article(self, title: str, *, refresh: bool = False) -> Article | None:
        """Fetch the current revision of ``title``; ``None`` if the page does not exist."""
        cache_file = self._cache_file(title)
        if cache_file is not None and not refresh:
            cached = _read_cache(cache_file)
            if cached is not None:
                return cached

        payload = self._get(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "prop": "extracts|revisions",
                "explaintext": "1",
                "exsectionformat": "wiki",
                "rvprop": "ids",
                "titles": title,
            }
        )
        try:
            page: dict[str, Any] = payload["query"]["pages"][0]
            if page.get("missing") or page.get("invalid"):
                return None
            canonical = str(page["title"])
            article = Article(
                title=canonical,
                revision_id=int(page["revisions"][0]["revid"]),
                text=str(page.get("extract", "")),
                url=f"{self._site_url}/wiki/{quote(canonical.replace(' ', '_'))}",
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise WikipediaError(f"Unexpected API response for {title!r}") from exc

        if cache_file is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = cache_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(asdict(article), ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_file, cache_file)
        return article

    def _cache_file(self, title: str) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{hashlib.sha256(title.encode('utf-8')).hexdigest()}.json"

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            self._throttle()
            retry_after = 0.0
            try:
                response = self._http.get(self._api_url, params=params)
            except httpx.TransportError as exc:
                error = exc
            else:
                if response.status_code == 200:
                    try:
                        data: object = response.json()
                    except ValueError:
                        data = None
                    if isinstance(data, dict):
                        return data
                    error = WikipediaError("Invalid JSON response")
                elif response.status_code not in RETRYABLE_STATUS:
                    raise WikipediaError(f"HTTP {response.status_code} for {params['titles']!r}")
                else:
                    error = WikipediaError(f"HTTP {response.status_code}")
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            if attempt < self._max_attempts:
                self._sleep(max(2.0**attempt, retry_after))
        raise WikipediaError(
            f"Giving up on {params['titles']!r} after {self._max_attempts} attempts: {error}"
        )

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self._last_request_at + self._min_interval_s - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()


def _read_cache(cache_file: Path) -> Article | None:
    """Return the cached article, or ``None`` if the entry is absent, unreadable or invalid."""
    try:
        article = Article(**json.loads(cache_file.read_text(encoding="utf-8")))
    except (ValueError, TypeError, OSError):
        return None
    return article


def _parse_retry_after(value: str | None) -> float:
    """Seconds to wait, clamped to ``[0, MAX_RETRY_AFTER_S]``; unparseable or NaN gives 0."""
    try:
        seconds = float(value) if value else 0.0
    except ValueError:
        return 0.0
    if math.isnan(seconds):
        return 0.0
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_S)
