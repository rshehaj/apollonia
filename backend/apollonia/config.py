"""Application settings, loaded from ``APOLLONIA_*`` environment variables or ``.env``."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_TOPICS_PATH = BACKEND_DIR / "data" / "topics.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APOLLONIA_", env_file=BACKEND_DIR / ".env", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://apollonia:apollonia@localhost:5433/apollonia"

    embedder: Literal["bge-m3", "fake"] = "bge-m3"
    embedding_model: str = "BAAI/bge-m3"

    wikipedia_api_url: str = "https://sq.wikipedia.org/w/api.php"
    wikipedia_user_agent: str = (
        "Apollonia/0.1 (set APOLLONIA_WIKIPEDIA_USER_AGENT to add a contact)"
    )
    wikipedia_min_interval_s: float = 1.0
    cache_dir: Path = BACKEND_DIR / ".cache"

    topics_path: Path = DEFAULT_TOPICS_PATH

    chunk_target_tokens: int = 400
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 50

    search_candidates: int = 20
    search_k: int = 6


def get_settings() -> Settings:
    return Settings()
