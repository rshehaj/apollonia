import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from apollonia.api import routes
from apollonia.api.app import create_app
from apollonia.config import Settings
from apollonia.embeddings import FakeEmbedder

# Nothing listens on port 1: requests that reach the database fail with OperationalError.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://u:p@127.0.0.1:1/x"


@pytest.fixture
def offline_client(embedder: FakeEmbedder) -> Iterator[TestClient]:
    """A client without a database, for behaviour decided before the database is touched."""
    settings = Settings(database_url=UNREACHABLE_DATABASE_URL, embedder="fake")
    with TestClient(create_app(settings, embedder=embedder)) as test_client:
        yield test_client


@pytest.fixture
def client(
    seeded_session: Session, database_url: str, embedder: FakeEmbedder
) -> Iterator[TestClient]:
    app = create_app(Settings(database_url=database_url, embedder="fake"), embedder=embedder)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def unmigrated_database_url(database_url: str) -> Iterator[str]:
    """A reachable database on the test server without any migrations applied."""
    name = "apollonia_unmigrated"
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
            connection.execute(text(f"CREATE DATABASE {name}"))
        yield make_url(database_url).set(database=name).render_as_string(hide_password=False)
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    finally:
        admin.dispose()


@pytest.fixture
def unmigrated_client(unmigrated_database_url: str, embedder: FakeEmbedder) -> Iterator[TestClient]:
    settings = Settings(database_url=unmigrated_database_url, embedder="fake")
    with TestClient(create_app(settings, embedder=embedder)) as test_client:
        yield test_client


@pytest.mark.integration
def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "embedder": "ok"}


@pytest.mark.integration
def test_health_reports_unmigrated_database_as_unavailable(unmigrated_client: TestClient) -> None:
    response = unmigrated_client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable", "embedder": "ok"}


def test_health_reports_schema_error_as_unavailable(embedder: FakeEmbedder) -> None:
    class BrokenSession:
        def execute(self, *args: object, **kwargs: object) -> None:
            raise ProgrammingError("SELECT 1 FROM chunks", {}, Exception("no such table"))

    settings = Settings(database_url=UNREACHABLE_DATABASE_URL, embedder="fake")
    app = create_app(settings, embedder=embedder)
    app.dependency_overrides[routes.get_session] = lambda: BrokenSession()
    with TestClient(app) as test_client:
        response = test_client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable", "embedder": "ok"}


@pytest.mark.integration
def test_search_returns_ranked_chunks(client: TestClient) -> None:
    response = client.get(
        "/search", params={"q": "Kush e mbrojti Krujën nga ushtria osmane?", "k": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "hybrid"
    assert len(body["results"]) == 2
    assert body["results"][0]["title"] == "Skënderbeu"
    assert body["results"][0]["permalink"].endswith("oldid=102")


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["hybrid", "vector", "keyword"])
def test_search_supports_every_mode(client: TestClient, mode: str) -> None:
    response = client.get("/search", params={"q": "Skënderbeu Kruja", "mode": mode})

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == mode
    assert body["results"]
    if mode == "keyword":
        assert all(hit["vector_similarity"] is None for hit in body["results"])
    else:
        assert all(isinstance(hit["vector_similarity"], float) for hit in body["results"])


@pytest.mark.integration
def test_search_with_punctuation_only_query_returns_json(client: TestClient) -> None:
    # No keyword terms and no words for the embedder: must still be valid JSON, never NaN.
    response = client.get("/search", params={"q": "?!"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "?!"
    assert body["results"]  # vector-only fallback still ranks chunks


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": "\t\n"},
        {"q": "x", "k": 0},
        {"q": "x", "k": 21},
        {"q": "x" * 501},
        {"q": "x", "mode": "bm25"},
    ],
)
def test_search_rejects_invalid_input(offline_client: TestClient, params: dict[str, Any]) -> None:
    # Validation runs before the database is touched, so no 503 here despite the outage.
    response = offline_client.get("/search", params=params)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_search_passes_original_query_text(
    offline_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def fake_search(session: object, embedder: object, query: str, **kwargs: object) -> list[Any]:
        seen.append(query)
        return []

    monkeypatch.setattr(routes, "search", fake_search)
    response = offline_client.get("/search", params={"q": " Prizreni "})

    assert response.status_code == 200
    assert seen == [" Prizreni "]
    assert response.json()["query"] == " Prizreni "


def test_unexpected_database_error_returns_generic_500(
    offline_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing_search(*args: object, **kwargs: object) -> list[Any]:
        raise ProgrammingError("SELECT secret_sql", {}, Exception("relation does not exist"))

    monkeypatch.setattr(routes, "search", failing_search)
    with caplog.at_level(logging.ERROR, logger="apollonia.api"):
        response = offline_client.get("/search", params={"q": "Prizren"})

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Internal server error"}
    assert "secret_sql" not in response.text
    assert "relation does not exist" not in response.text
    assert any(record.name == "apollonia.api" and record.exc_info for record in caplog.records)


@pytest.mark.integration
def test_unmigrated_database_search_returns_generic_500(unmigrated_client: TestClient) -> None:
    response = unmigrated_client.get("/search", params={"q": "Prizren"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


def test_database_outage_returns_503(offline_client: TestClient) -> None:
    assert offline_client.get("/health").status_code == 503
    response = offline_client.get("/search", params={"q": "Prizren"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
