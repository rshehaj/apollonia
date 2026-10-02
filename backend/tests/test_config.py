from pathlib import Path

import pytest

from apollonia.config import BACKEND_DIR, DEFAULT_TOPICS_PATH, REPO_ROOT, Settings


def test_settings_read_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # make sure no local .env file is picked up
    monkeypatch.setenv("APOLLONIA_DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("APOLLONIA_EMBEDDER", "fake")

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.embedder == "fake"


def test_defaults_are_consistent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.topics_path == DEFAULT_TOPICS_PATH == BACKEND_DIR / "data" / "topics.yaml"
    assert REPO_ROOT / "backend" == BACKEND_DIR
    assert settings.chunk_overlap_tokens < settings.chunk_target_tokens <= settings.chunk_max_tokens
    assert settings.search_k <= settings.search_candidates
