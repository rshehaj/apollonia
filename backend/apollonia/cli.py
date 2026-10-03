"""Command-line interface: ``apollonia --help``."""

import functools
import hashlib
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
import yaml
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from apollonia import __version__
from apollonia.config import REPO_ROOT, Settings, get_settings
from apollonia.db.migrate import upgrade
from apollonia.db.session import make_engine, make_session_factory
from apollonia.embeddings import Embedder, create_embedder
from apollonia.evaluation.retrieval import (
    RETRIEVAL_DATASET,
    RetrievalCase,
    load_retrieval_cases,
    render_markdown,
    run_retrieval_eval,
)
from apollonia.ingest.chunk import ChunkingConfig
from apollonia.ingest.pipeline import ArticleSource, run_ingest
from apollonia.ingest.wikipedia import WikipediaClient
from apollonia.retrieval.search import SearchMode, search
from apollonia.topics import Topic, load_topics

app = typer.Typer(help="Apollonia — AI tutor for the Albanian Matura exam.", no_args_is_help=True)
db_app = typer.Typer(help="Database management.", no_args_is_help=True)
eval_app = typer.Typer(help="Quality evaluations.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(eval_app, name="eval")

ERROR_EXIT_CODE = 3
SNIPPET_CHARS = 200


class CliError(Exception):
    """An expected operational failure, reported as one line without a traceback."""


def friendly_errors[**P, R](command: Callable[P, R]) -> Callable[P, R]:
    """Turn expected operational failures into ``Error: ...`` on stderr and exit code 3.

    Unexpected exceptions propagate unchanged.
    """

    @functools.wraps(command)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return command(*args, **kwargs)
        except OperationalError:
            message = database_unreachable_message(get_settings().database_url)
        except CliError as exc:
            message = str(exc)
        typer.echo(f"Error: {message}", err=True)
        raise typer.Exit(code=ERROR_EXIT_CODE)

    return wrapper


def database_unreachable_message(database_url: str) -> str:
    url = make_url(database_url)  # never print the password
    return (
        f"cannot connect to the database at {url.host}:{url.port}. "
        "Is it running? (docker compose up -d db)"
    )


def check_database(engine: Engine) -> None:
    """Fail fast before slow work (fetching, loading the model) if the database is down."""
    with engine.connect():
        pass


def read_topics(path: Path) -> list[Topic]:
    try:
        return load_topics(path)
    except FileNotFoundError as exc:
        raise CliError(f"topics file not found: {path}") from exc
    except (ValueError, yaml.YAMLError) as exc:  # includes pydantic.ValidationError
        first_line = (str(exc).splitlines() or [""])[0]
        raise CliError(f"invalid topics file {path}: {first_line}") from exc


def read_retrieval_cases(path: Path) -> list[RetrievalCase]:
    try:
        return load_retrieval_cases(path)
    except FileNotFoundError as exc:
        raise CliError(f"dataset file not found: {path}") from exc
    except (ValueError, yaml.YAMLError) as exc:  # includes pydantic.ValidationError
        first_line = (str(exc).splitlines() or [""])[0]
        raise CliError(f"invalid dataset file {path}: {first_line}") from exc


def load_embedder(settings: Settings) -> Embedder:
    try:
        return create_embedder(settings)
    except RuntimeError as exc:  # e.g. the bge-m3 extra is not installed
        raise CliError(str(exc)) from exc


def format_snippet(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= SNIPPET_CHARS:
        return collapsed
    return collapsed[:SNIPPET_CHARS] + "…"


def build_article_source(settings: Settings) -> ArticleSource:
    return WikipediaClient(
        api_url=settings.wikipedia_api_url,
        user_agent=settings.wikipedia_user_agent,
        cache_dir=settings.cache_dir / "wikipedia",
        min_interval_s=settings.wikipedia_min_interval_s,
    )


def chunking_config(settings: Settings) -> ChunkingConfig:
    return ChunkingConfig(
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )


@db_app.command("upgrade")
@friendly_errors
def db_upgrade() -> None:
    """Create or migrate the database schema."""
    upgrade(get_settings().database_url)
    typer.echo("Database schema is up to date.")


@app.command()
@friendly_errors
def ingest(
    topic: Annotated[
        list[str] | None,
        typer.Option("--topic", "-t", help="Only ingest this topic id (repeatable)."),
    ] = None,
    refresh: Annotated[bool, typer.Option(help="Bypass the local Wikipedia cache.")] = False,
) -> None:
    """Fetch, chunk, embed and store the articles listed in the topic map."""
    settings = get_settings()
    topics = read_topics(settings.topics_path)
    if topic:
        unknown = sorted(set(topic) - {t.id for t in topics})
        if unknown:
            raise typer.BadParameter(
                f"Unknown topic id(s): {', '.join(unknown)}", param_hint="--topic"
            )
        topics = [t for t in topics if t.id in topic]

    engine = make_engine(settings.database_url)
    check_database(engine)
    embedder = load_embedder(settings)
    source = build_article_source(settings)
    session_factory = make_session_factory(engine)
    try:
        with session_factory() as session:
            report = run_ingest(
                session,
                source,
                topics,
                embedder,
                chunking_config(settings),
                refresh=refresh,
                prune=not topic,  # only a full run knows which documents are stale
                on_progress=typer.echo,
            )
    finally:
        if isinstance(source, WikipediaClient):
            source.close()

    typer.echo(report.summary())
    if report.failed:
        raise typer.Exit(code=1)


@app.command("search")
@friendly_errors
def search_command(
    query: Annotated[str, typer.Argument(help="Question or keywords, in Albanian.")],
    k: Annotated[
        int | None,
        typer.Option(
            min=1,
            max=50,
            show_default=False,
            help="Number of results (default: APOLLONIA_SEARCH_K, 6 unless set).",
        ),
    ] = None,
    mode: Annotated[SearchMode, typer.Option(help="Retrieval strategy.")] = SearchMode.HYBRID,
) -> None:
    """Search the knowledge base."""
    if not query.strip():
        raise typer.BadParameter("query must not be empty", param_hint="QUERY")
    settings = get_settings()
    if k is None:
        k = settings.search_k
    engine = make_engine(settings.database_url)
    check_database(engine)
    embedder = load_embedder(settings)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        results = search(
            session, embedder, query, k=k, candidates=settings.search_candidates, mode=mode
        )
    if not results:
        typer.echo("No results.")
        return
    for rank, result in enumerate(results, start=1):
        snippet = format_snippet(result.text)
        typer.echo(f"{rank}. [{result.score:.4f}] {result.section_path}")
        typer.echo(f"   {snippet}")
        typer.echo(f"   {result.permalink}")


@eval_app.command("retrieval")
@friendly_errors
def eval_retrieval(
    dataset: Annotated[Path, typer.Option(help="Evaluation dataset (YAML).")] = RETRIEVAL_DATASET,
    output: Annotated[
        Path | None, typer.Option(help="Report path (default: docs/evals/retrieval-<date>.md).")
    ] = None,
    depth: Annotated[int, typer.Option(min=5, max=50, help="Results inspected per query.")] = 10,
) -> None:
    """Measure recall@k and MRR for vector, keyword and hybrid retrieval."""
    settings = get_settings()
    cases = read_retrieval_cases(dataset)
    engine = make_engine(settings.database_url)
    check_database(engine)
    embedder = load_embedder(settings)
    model_name = settings.embedding_model if settings.embedder == "bge-m3" else settings.embedder
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        report = run_retrieval_eval(
            session,
            embedder,
            cases,
            depth=depth,
            candidates=settings.search_candidates,
            embedding_model=model_name,
            dataset_name=dataset.name,
            dataset_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest()[:12],
            chunking=chunking_config(settings),
            apollonia_version=__version__,
        )

    target = output or REPO_ROOT / "docs" / "evals" / f"retrieval-{date.today().isoformat()}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(report), encoding="utf-8")
    for result in report.results:
        typer.echo(
            f"{result.mode.value:>8}  recall@5={result.recall(5):.2f}  "
            f"mrr@{depth}={result.mrr(depth):.2f}"
        )
    if report.missing_labels:
        typer.echo(
            f"Warning: {len(report.missing_labels)} expected title(s) not in the corpus: "
            f"{', '.join(report.missing_labels)}",
            err=True,
        )
    typer.echo(f"Report written to {target}")
