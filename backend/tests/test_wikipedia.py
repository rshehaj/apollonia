from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from apollonia.ingest.wikipedia import (
    Article,
    WikipediaClient,
    WikipediaError,
    revision_permalink,
)

API = "https://sq.wikipedia.org/w/api.php"
Handler = Callable[[httpx.Request], httpx.Response]


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def page_payload(
    title: str = "Lidhja e Prizrenit", revid: int = 2996079, extract: str = "Tekst."
) -> dict[str, Any]:
    page = {
        "pageid": 1,
        "ns": 0,
        "title": title,
        "extract": extract,
        "revisions": [{"revid": revid}],
    }
    return {"query": {"pages": [page]}}


def make_client(
    handler: Handler, cache_dir: Path | None = None, time: FakeTime | None = None
) -> WikipediaClient:
    time = time or FakeTime()
    return WikipediaClient(
        api_url=API,
        user_agent="ApolloniaTests/1.0 (test@example.com)",
        cache_dir=cache_dir,
        transport=httpx.MockTransport(handler),
        sleep=time.sleep,
        clock=time.clock,
    )


def test_fetch_article_returns_canonical_title_revision_and_text() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=page_payload("Skënderbeu", 42, "Heroi kombëtar."))

    article = make_client(handler).fetch_article("Gjergj Kastrioti Skënderbeu")

    assert article == Article(
        title="Skënderbeu",
        revision_id=42,
        text="Heroi kombëtar.",
        url="https://sq.wikipedia.org/wiki/Sk%C3%ABnderbeu",
    )
    params = requests[0].url.params
    assert params["titles"] == "Gjergj Kastrioti Skënderbeu"
    assert params["redirects"] == "1"
    assert params["explaintext"] == "1"
    assert params["exsectionformat"] == "wiki"
    assert requests[0].headers["User-Agent"] == "ApolloniaTests/1.0 (test@example.com)"


def test_missing_article_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": {"pages": [{"title": "X", "missing": True}]}})

    assert make_client(handler).fetch_article("X") is None


def test_cache_avoids_repeat_requests_unless_refreshed(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=page_payload())

    client = make_client(handler, cache_dir=tmp_path)
    first = client.fetch_article("Lidhja e Prizrenit")
    second = client.fetch_article("Lidhja e Prizrenit")
    assert first == second
    assert len(calls) == 1

    client.fetch_article("Lidhja e Prizrenit", refresh=True)
    assert len(calls) == 2


def test_rate_limited_request_is_retried_honouring_retry_after() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "5"}),
            httpx.Response(200, json=page_payload()),
        ]
    )
    time = FakeTime()

    article = make_client(lambda request: next(responses), time=time).fetch_article(
        "Lidhja e Prizrenit"
    )

    assert article is not None
    assert time.sleeps == [5.0]


def test_transport_errors_are_retried() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json=page_payload())

    time = FakeTime()
    assert make_client(handler, time=time).fetch_article("Lidhja e Prizrenit") is not None
    assert time.sleeps == [2.0]


def test_gives_up_after_three_attempts_with_exponential_backoff() -> None:
    time = FakeTime()
    client = make_client(lambda request: httpx.Response(503), time=time)

    with pytest.raises(WikipediaError, match="3 attempts"):
        client.fetch_article("Lidhja e Prizrenit")
    assert time.sleeps == [2.0, 4.0]


def test_client_errors_are_not_retried() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(404)

    with pytest.raises(WikipediaError, match="HTTP 404"):
        make_client(handler).fetch_article("Lidhja e Prizrenit")
    assert len(calls) == 1


def test_unexpected_payload_raises_wikipedia_error() -> None:
    client = make_client(lambda request: httpx.Response(200, json={"error": {"code": "x"}}))
    with pytest.raises(WikipediaError, match="Unexpected API response"):
        client.fetch_article("Lidhja e Prizrenit")


def test_consecutive_requests_are_throttled() -> None:
    time = FakeTime()
    client = make_client(lambda request: httpx.Response(200, json=page_payload()), time=time)

    client.fetch_article("A")
    client.fetch_article("B")

    assert time.sleeps == [1.0]


def test_revision_permalink() -> None:
    assert (
        revision_permalink("https://sq.wikipedia.org/wiki/Lidhja_e_Prizrenit", 2996079)
        == "https://sq.wikipedia.org/w/index.php?title=Lidhja_e_Prizrenit&oldid=2996079"
    )


def test_non_json_200_response_is_retried_then_gives_up() -> None:
    time = FakeTime()
    client = make_client(lambda request: httpx.Response(200, text="<html>error</html>"), time=time)

    with pytest.raises(WikipediaError, match="3 attempts"):
        client.fetch_article("Lidhja e Prizrenit")
    assert time.sleeps == [2.0, 4.0]


def test_non_object_json_200_response_is_retried() -> None:
    responses = iter([httpx.Response(200, json=[1, 2]), httpx.Response(200, json=page_payload())])
    time = FakeTime()

    article = make_client(lambda request: next(responses), time=time).fetch_article(
        "Lidhja e Prizrenit"
    )

    assert article is not None
    assert time.sleeps == [2.0]


def _corrupt_cache_and_refetch(tmp_path: Path, corrupt: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=page_payload())

    client = make_client(handler, cache_dir=tmp_path)
    expected = client.fetch_article("Lidhja e Prizrenit")
    (cache_file,) = tmp_path.iterdir()
    cache_file.write_text(corrupt, encoding="utf-8")

    assert client.fetch_article("Lidhja e Prizrenit") == expected
    assert len(calls) == 2
    assert client.fetch_article("Lidhja e Prizrenit") == expected
    assert len(calls) == 2  # the corrupt entry was overwritten


def test_truncated_cache_entry_is_treated_as_a_miss(tmp_path: Path) -> None:
    _corrupt_cache_and_refetch(tmp_path, '{"title": "Lidhja e Prizr')


def test_cache_entry_with_missing_fields_is_treated_as_a_miss(tmp_path: Path) -> None:
    _corrupt_cache_and_refetch(tmp_path, '{"title": "X"}')


def test_cache_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    client = make_client(
        lambda request: httpx.Response(200, json=page_payload()), cache_dir=tmp_path
    )
    client.fetch_article("Lidhja e Prizrenit")
    assert [p.suffix for p in tmp_path.iterdir()] == [".json"]


@pytest.mark.parametrize(
    ("retry_after", "expected_sleep"),
    [("3600", 60.0), ("inf", 60.0), ("nan", 2.0), ("-5", 2.0)],
)
def test_retry_after_is_clamped(retry_after: str, expected_sleep: float) -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": retry_after}),
            httpx.Response(200, json=page_payload()),
        ]
    )
    time = FakeTime()

    article = make_client(lambda request: next(responses), time=time).fetch_article(
        "Lidhja e Prizrenit"
    )

    assert article is not None
    assert time.sleeps == [expected_sleep]
