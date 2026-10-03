import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

import apollonia
from apollonia import cli
from apollonia.config import Settings
from apollonia.ingest.wikipedia import WikipediaError
from tests.support import SAMPLE_ARTICLES, FakeArticleSource

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


@pytest.mark.integration
@pytest.mark.usefixtures("session")
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


@pytest.mark.integration
@pytest.mark.usefixtures("session")
def test_search_default_k_comes_from_settings(
    cli_env: FakeArticleSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runner.invoke(cli.app, ["ingest"]).exit_code == 0
    monkeypatch.setenv("APOLLONIA_SEARCH_K", "2")

    result = runner.invoke(cli.app, ["search", "Skënderbeu Kruja"])

    assert result.exit_code == 0, result.output
    assert "2. [" in result.output
    assert "3. [" not in result.output


@pytest.mark.integration
@pytest.mark.usefixtures("session")
def test_ingest_single_topic_does_not_prune(cli_env: FakeArticleSource) -> None:
    assert runner.invoke(cli.app, ["ingest"]).exit_code == 0

    result = runner.invoke(cli.app, ["ingest", "--topic", "skenderbeu"])

    assert result.exit_code == 0, result.output
    assert "1 unchanged" in result.output
    assert "Pruned" not in result.output


@pytest.mark.integration
@pytest.mark.usefixtures("session")
def test_ingest_rejects_unknown_topic(cli_env: FakeArticleSource) -> None:
    result = runner.invoke(cli.app, ["ingest", "--topic", "nuk-ekziston"])
    assert result.exit_code == 2
    assert "nuk-ekziston" in result.output


@pytest.mark.integration
@pytest.mark.usefixtures("session")
def test_db_upgrade_is_idempotent(cli_env: FakeArticleSource) -> None:
    result = runner.invoke(cli.app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output


@pytest.mark.integration
@pytest.mark.usefixtures("session")
def test_ingest_exits_1_when_an_article_fails(cli_env: FakeArticleSource) -> None:
    cli_env._articles["Skënderbeu"] = WikipediaError("HTTP 503")

    result = runner.invoke(cli.app, ["ingest"])

    assert result.exit_code == 1, result.output
    assert "Failed: Skënderbeu" in result.output
    assert "Ingested 2 articles" in result.output


@pytest.mark.integration
@pytest.mark.usefixtures("session")
def test_search_on_empty_database(cli_env: FakeArticleSource) -> None:
    result = runner.invoke(cli.app, ["search", "Skënderbeu"])
    assert result.exit_code == 0, result.output
    assert "No results." in result.output


@pytest.mark.integration
@pytest.mark.usefixtures("session")
def test_eval_retrieval_writes_report(cli_env: FakeArticleSource, tmp_path: Path) -> None:
    assert runner.invoke(cli.app, ["ingest"]).exit_code == 0
    dataset = tmp_path / "cases.yaml"
    dataset.write_text(
        "- id: q1\n  question: Kush e mbrojti Krujën nga ushtria osmane?\n"
        "  expected: [{title: Skënderbeu}]\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.md"

    result = runner.invoke(
        cli.app, ["eval", "retrieval", "--dataset", str(dataset), "--output", str(output)]
    )

    assert result.exit_code == 0, result.output
    report = output.read_text(encoding="utf-8")
    assert "| hybrid | 1.00 | 1.00 | 1.00 |" in report
    expected_sha = hashlib.sha256(dataset.read_bytes()).hexdigest()[:12]
    assert f"sha256 `{expected_sha}`" in report
    assert f"| Apollonia version | `{apollonia.__version__}` |" in report
    assert "Warning" not in result.output


@pytest.mark.integration
@pytest.mark.usefixtures("session")
def test_eval_retrieval_warns_about_labels_not_in_corpus(
    cli_env: FakeArticleSource, tmp_path: Path
) -> None:
    assert runner.invoke(cli.app, ["ingest"]).exit_code == 0
    dataset = tmp_path / "cases.yaml"
    dataset.write_text(
        "- id: q1\n  question: Çfarë është fotosinteza?\n  expected: [{title: Fotosinteza}]\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        cli.app,
        ["eval", "retrieval", "--dataset", str(dataset), "--output", str(tmp_path / "r.md")],
    )

    assert result.exit_code == 0, result.output
    assert "Warning: 1 expected title(s) not in the corpus: Fotosinteza" in result.output


# --- Operational errors: no Docker needed -------------------------------------------------

UNREACHABLE_DATABASE_URL = "postgresql+psycopg://u:secret@127.0.0.1:1/x"


@pytest.fixture
def offline_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    topics = tmp_path / "topics.yaml"
    topics.write_text(TOPICS_YAML, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APOLLONIA_DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("APOLLONIA_EMBEDDER", "fake")
    monkeypatch.setenv("APOLLONIA_TOPICS_PATH", str(topics))

    def no_source(settings: Settings) -> FakeArticleSource:
        raise AssertionError("articles must not be fetched when the database is down")

    monkeypatch.setattr(cli, "build_article_source", no_source)
    return tmp_path


def assert_friendly_db_error(output: str) -> None:
    assert "cannot connect to the database" in output
    assert "127.0.0.1:1" in output
    assert "secret" not in output
    assert "Traceback" not in output


def test_search_reports_unreachable_database(offline_env: Path) -> None:
    result = runner.invoke(cli.app, ["search", "x"])
    assert result.exit_code == 3, result.output
    assert_friendly_db_error(result.output)


@pytest.mark.parametrize("query", ["", "   "])
def test_search_rejects_empty_query(
    offline_env: Path, monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    def no_engine(url: str) -> None:
        raise AssertionError("the database must not be touched for an empty query")

    monkeypatch.setattr(cli, "make_engine", no_engine)

    result = runner.invoke(cli.app, ["search", query])

    assert result.exit_code == 2, result.output
    assert "query must not be empty" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("k", ["0", "51"])
def test_search_rejects_k_out_of_range(offline_env: Path, k: str) -> None:
    result = runner.invoke(cli.app, ["search", "x", "--k", k])
    assert result.exit_code == 2, result.output


def test_ingest_checks_database_before_fetching(offline_env: Path) -> None:
    result = runner.invoke(cli.app, ["ingest"])
    assert result.exit_code == 3, result.output
    assert_friendly_db_error(result.output)


def test_db_upgrade_reports_unreachable_database(offline_env: Path) -> None:
    result = runner.invoke(cli.app, ["db", "upgrade"])
    assert result.exit_code == 3, result.output
    assert_friendly_db_error(result.output)


def test_ingest_reports_missing_topics_file(
    offline_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = offline_env / "missing.yaml"
    monkeypatch.setenv("APOLLONIA_TOPICS_PATH", str(missing))

    result = runner.invoke(cli.app, ["ingest"])

    assert result.exit_code == 3, result.output
    assert f"topics file not found: {missing}" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "content",
    [
        "- id: a\n  name: A\n  articles: 5\n",  # schema violation
        "- {id: a, name: A, articles: [X]\n",  # YAML syntax error
    ],
)
def test_ingest_reports_invalid_topics_file(offline_env: Path, content: str) -> None:
    (offline_env / "topics.yaml").write_text(content, "utf-8")

    result = runner.invoke(cli.app, ["ingest"])

    assert result.exit_code == 3, result.output
    assert "invalid topics file" in result.output
    assert len(result.output.strip().splitlines()) == 1


def test_unexpected_errors_still_raise(offline_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(path: Path) -> None:
        raise KeyError("boom")

    monkeypatch.setattr(cli, "load_topics", boom)

    result = runner.invoke(cli.app, ["ingest"])

    assert result.exit_code == 1
    assert isinstance(result.exception, KeyError)


def test_snippet_whitespace_is_collapsed() -> None:
    assert cli.format_snippet("a\n\n  b\tc") == "a b c"
    long = "word " * 100
    snippet = cli.format_snippet(long)
    assert snippet.endswith("…")
    assert len(snippet) == 201


def test_eval_retrieval_reports_unreachable_database(offline_env: Path) -> None:
    result = runner.invoke(cli.app, ["eval", "retrieval", "--output", str(offline_env / "r.md")])
    assert result.exit_code == 3, result.output
    assert_friendly_db_error(result.output)
    assert not (offline_env / "r.md").exists()


def test_eval_retrieval_reports_missing_dataset(offline_env: Path) -> None:
    missing = offline_env / "missing.yaml"

    result = runner.invoke(cli.app, ["eval", "retrieval", "--dataset", str(missing)])

    assert result.exit_code == 3, result.output
    assert f"dataset file not found: {missing}" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "content",
    [
        "- {id: q1, question: A?, expected: [{title: X}]}\n",  # YAML syntax error
        "- id: q1\n  question: A?\n  expected: []\n",  # schema violation
        "- {id: q1, question: 'A?', expected: [{title: X}]}\n" * 2,  # duplicate ids
    ],
)
def test_eval_retrieval_reports_invalid_dataset(offline_env: Path, content: str) -> None:
    dataset = offline_env / "cases.yaml"
    dataset.write_text(content, encoding="utf-8")

    result = runner.invoke(cli.app, ["eval", "retrieval", "--dataset", str(dataset)])

    assert result.exit_code == 3, result.output
    assert f"invalid dataset file {dataset}" in result.output
    assert len(result.output.strip().splitlines()) == 1
