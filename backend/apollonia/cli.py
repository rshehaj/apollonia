"""Command-line interface: ``apollonia --help``."""

from typing import Annotated

import typer

from apollonia.config import Settings, get_settings
from apollonia.db.migrate import upgrade
from apollonia.db.session import make_engine, make_session_factory
from apollonia.embeddings import create_embedder
from apollonia.ingest.chunk import ChunkingConfig
from apollonia.ingest.pipeline import ArticleSource, run_ingest
from apollonia.ingest.wikipedia import WikipediaClient
from apollonia.retrieval.search import SearchMode, search
from apollonia.topics import load_topics

app = typer.Typer(help="Apollonia — AI tutor for the Albanian Matura exam.", no_args_is_help=True)
db_app = typer.Typer(help="Database management.", no_args_is_help=True)
eval_app = typer.Typer(help="Quality evaluations.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(eval_app, name="eval")


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
def db_upgrade() -> None:
    """Create or migrate the database schema."""
    upgrade(get_settings().database_url)
    typer.echo("Database schema is up to date.")


@app.command()
def ingest(
    topic: Annotated[
        list[str] | None,
        typer.Option("--topic", "-t", help="Only ingest this topic id (repeatable)."),
    ] = None,
    refresh: Annotated[bool, typer.Option(help="Bypass the local Wikipedia cache.")] = False,
) -> None:
    """Fetch, chunk, embed and store the articles listed in the topic map."""
    settings = get_settings()
    topics = load_topics(settings.topics_path)
    if topic:
        unknown = sorted(set(topic) - {t.id for t in topics})
        if unknown:
            raise typer.BadParameter(
                f"Unknown topic id(s): {', '.join(unknown)}", param_hint="--topic"
            )
        topics = [t for t in topics if t.id in topic]

    embedder = create_embedder(settings)
    source = build_article_source(settings)
    session_factory = make_session_factory(make_engine(settings.database_url))
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
def search_command(
    query: Annotated[str, typer.Argument(help="Question or keywords, in Albanian.")],
    k: Annotated[int, typer.Option(min=1, max=50, help="Number of results.")] = 6,
    mode: Annotated[SearchMode, typer.Option(help="Retrieval strategy.")] = SearchMode.HYBRID,
) -> None:
    """Search the knowledge base."""
    settings = get_settings()
    embedder = create_embedder(settings)
    session_factory = make_session_factory(make_engine(settings.database_url))
    with session_factory() as session:
        results = search(
            session, embedder, query, k=k, candidates=settings.search_candidates, mode=mode
        )
    if not results:
        typer.echo("No results.")
        return
    for rank, result in enumerate(results, start=1):
        snippet = result.text if len(result.text) <= 200 else result.text[:200] + "…"
        typer.echo(f"{rank}. [{result.score:.4f}] {result.section_path}")
        typer.echo(f"   {snippet}")
        typer.echo(f"   {result.permalink}")
