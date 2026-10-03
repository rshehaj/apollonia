from collections.abc import Iterator
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import AfterValidator, BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from apollonia.config import Settings
from apollonia.embeddings import Embedder
from apollonia.retrieval.search import SearchMode, search

router = APIRouter()


def get_session(request: Request) -> Iterator[Session]:
    factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with factory() as session:
        yield session


def get_embedder(request: Request) -> Embedder:
    return cast(Embedder, request.app.state.embedder)


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


SessionDep = Annotated[Session, Depends(get_session)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def _require_text(value: str) -> str:
    """Reject whitespace-only queries; the original text is passed on unchanged."""
    if not value.strip():
        raise ValueError("Query must contain non-whitespace characters")
    return value


QueryText = Annotated[
    str,
    Query(min_length=1, max_length=500, description="Question or keywords"),
    AfterValidator(_require_text),
]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    embedder: Literal["ok"]


class SearchHit(BaseModel):
    chunk_id: int
    title: str
    section_path: str
    text: str
    url: str
    permalink: str
    revision_id: int
    score: float
    vector_similarity: float | None


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    results: list[SearchHit]


@router.get("/health", response_model=HealthResponse)
def health(response: Response, session: SessionDep) -> HealthResponse:
    """Report whether the API can serve searches.

    The database check queries the ``chunks`` table, so a reachable database without the
    migrations applied reports ``unavailable``. ``"embedder": "ok"`` means the embedding model
    was loaded at startup: a failed load aborts startup, so a running app always has one.
    """
    try:
        session.execute(text("SELECT 1 FROM chunks LIMIT 1"))
        database_ok = True
    except SQLAlchemyError:
        database_ok = False
    if not database_ok:
        response.status_code = 503
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        database="ok" if database_ok else "unavailable",
        embedder="ok",
    )


@router.get("/search", response_model=SearchResponse)
def search_chunks(
    q: QueryText,
    session: SessionDep,
    embedder: EmbedderDep,
    settings: SettingsDep,
    k: Annotated[
        int | None,
        Query(
            ge=1,
            le=20,
            description="Number of results. Defaults to the server configuration "
            "(APOLLONIA_SEARCH_K, 6 unless set).",
        ),
    ] = None,
    mode: SearchMode = SearchMode.HYBRID,
) -> SearchResponse:
    if k is None:
        k = settings.search_k
    results = search(session, embedder, q, k=k, candidates=settings.search_candidates, mode=mode)
    return SearchResponse(
        query=q,
        mode=mode,
        results=[
            SearchHit(
                chunk_id=r.chunk_id,
                title=r.document_title,
                section_path=r.section_path,
                text=r.text,
                url=r.url,
                permalink=r.permalink,
                revision_id=r.revision_id,
                score=r.score,
                vector_similarity=r.vector_similarity,
            )
            for r in results
        ],
    )
