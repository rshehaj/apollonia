from pathlib import Path

import pytest
from typer.testing import CliRunner

from apollonia import cli
from apollonia.config import Settings
from tests.support import SAMPLE_ARTICLES, FakeArticleSource

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("session")]

runner = CliRunner()

TOPICS_YAML = """\
- id: rilindja
  name: Rilindja Kombëtare
  articles: [Lidhja e Prizrenit, Kongresi i Manastirit]
- id: skenderbeu
  name: Skënderbeu
  articles: [Skënderbeu]
"""


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> FakeArticleSource:
    topics = tmp_path / "topics.yaml"
    topics.write_text(TOPICS_YAML, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APOLLONIA_DATABASE_URL", database_url)
    monkeypatch.setenv("APOLLONIA_EMBEDDER", "fake")
    monkeypatch.setenv("APOLLONIA_TOPICS_PATH", str(topics))
    source = FakeArticleSource({article.title: article for article in SAMPLE_ARTICLES})

    def fake_source(settings: Settings) -> FakeArticleSource:
        return source

    monkeypatch.setattr(cli, "build_article_source", fake_source)
    return source


def test_ingest_then_search(cli_env: FakeArticleSource) -> None:
    result = runner.invoke(cli.app, ["ingest"])
    assert result.exit_code == 0, result.output
    assert "Ingested 3 articles: 3 created" in result.output

    result = runner.invoke(
        cli.app, ["search", "Kush e mbrojti Krujën nga ushtria osmane?", "--k", "1"]
    )
    assert result.exit_code == 0, result.output
    assert "Skënderbeu > Rrethimi i Krujës" in result.output
    assert "oldid=102" in result.output


def test_ingest_single_topic_does_not_prune(cli_env: FakeArticleSource) -> None:
    assert runner.invoke(cli.app, ["ingest"]).exit_code == 0

    result = runner.invoke(cli.app, ["ingest", "--topic", "skenderbeu"])

    assert result.exit_code == 0, result.output
    assert "1 unchanged" in result.output
    assert "Pruned" not in result.output


def test_ingest_rejects_unknown_topic(cli_env: FakeArticleSource) -> None:
    result = runner.invoke(cli.app, ["ingest", "--topic", "nuk-ekziston"])
    assert result.exit_code == 2
    assert "nuk-ekziston" in result.output


def test_db_upgrade_is_idempotent(cli_env: FakeArticleSource) -> None:
    result = runner.invoke(cli.app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output
