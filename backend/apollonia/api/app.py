import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from apollonia import __version__
from apollonia.api.routes import router
from apollonia.config import Settings, get_settings
from apollonia.db.session import make_engine, make_session_factory
from apollonia.embeddings import Embedder, create_embedder

logger = logging.getLogger("apollonia.api")


def create_app(settings: Settings | None = None, embedder: Embedder | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(resolved.database_url)
        app.state.settings = resolved
        app.state.session_factory = make_session_factory(engine)
        app.state.embedder = embedder or create_embedder(resolved)  # loads the model once
        yield
        engine.dispose()

    app = FastAPI(title="Apollonia API", version=__version__, lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(OperationalError)
    async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    # Starlette picks the handler of the most specific class in the exception's MRO, so the
    # OperationalError handler above keeps priority over this catch-all for other DB errors.
    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception(
            "Database error while handling %s %s", request.method, request.url.path, exc_info=exc
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app
