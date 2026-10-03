"""Initial schema: documents, chunks and topic links.

Revision ID: 0001
Revises:
Create Date: 2026-10-02
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS unaccent",
    # unaccent() is only STABLE, and generated columns require IMMUTABLE functions.
    # Pinning the dictionary makes the result deterministic, so this wrapper is safe.
    """
    CREATE OR REPLACE FUNCTION apollonia_unaccent(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
    """,
    """
    CREATE TABLE documents (
        id bigserial PRIMARY KEY,
        title text NOT NULL UNIQUE,
        url text NOT NULL,
        revision_id bigint NOT NULL,
        content_hash varchar(64) NOT NULL,
        fetched_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE chunks (
        id bigserial PRIMARY KEY,
        document_id bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
        ordinal integer NOT NULL,
        section_path text NOT NULL,
        text text NOT NULL,
        embedding vector(1024) NOT NULL,
        content_hash varchar(64) NOT NULL,
        tsv tsvector GENERATED ALWAYS AS (
            to_tsvector('simple'::regconfig, apollonia_unaccent(section_path || ' ' || text))
        ) STORED,
        UNIQUE (document_id, ordinal)
    )
    """,
    "CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)",
    "CREATE INDEX ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)",
    """
    CREATE TABLE document_topics (
        document_id bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
        topic_id text NOT NULL,
        PRIMARY KEY (document_id, topic_id)
    )
    """,
    "CREATE INDEX ix_document_topics_topic_id ON document_topics (topic_id)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_topics, chunks, documents")
    op.execute("DROP FUNCTION IF EXISTS apollonia_unaccent(text)")
