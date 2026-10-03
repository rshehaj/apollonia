from alembic import command
from alembic.config import Config

from apollonia.config import BACKEND_DIR


def upgrade(database_url: str, revision: str = "head") -> None:
    """Apply migrations up to ``revision``."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # ConfigParser interpolates "%", so escape it (e.g. in URL-encoded passwords).
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, revision)
