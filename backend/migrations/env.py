from alembic import context
from sqlalchemy import create_engine, pool

from apollonia.config import get_settings
from apollonia.db.models import Base

url = context.config.get_main_option("sqlalchemy.url") or get_settings().database_url
engine = create_engine(url, poolclass=pool.NullPool)

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
