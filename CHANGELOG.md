# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-03

### Added

- **Knowledge base ingestion** of curated Albanian Wikipedia History articles, driven by a
  topic map (`backend/data/topics.yaml`): section parsing, section-aware chunking measured with
  the embedding model's tokenizer, and `BAAI/bge-m3` embeddings. Re-running ingestion only
  re-embeds articles whose revision or processed content changed; a full run prunes documents
  that left the topic map or no longer exist on Wikipedia, and skips pruning if any article
  failed.
- **Wikipedia client** for the MediaWiki Action API: identifies itself with a configurable
  User-Agent, rate-limits requests, retries transport errors, HTTP 429/5xx and invalid JSON
  responses with backoff, honours `Retry-After` (capped at 60 seconds), and keeps a local
  cache that is written atomically and ignores unreadable entries so they are fetched again.
  Every result links to the exact Wikipedia revision it came from.
- **PostgreSQL schema** (Alembic migrations) with pgvector: 1024-dimensional embeddings under an
  HNSW cosine index, and a generated, accent-folded full-text column (`simple` configuration +
  `unaccent`) under a GIN index.
- **Hybrid retrieval**: vector search and keyword search (accent-folded, stop words removed,
  terms OR-combined) merged with Reciprocal Rank Fusion; `vector` and `keyword` modes are
  available on their own.
- **Configurable result count**: `APOLLONIA_SEARCH_K` sets the default number of results for the
  CLI and the API (6 unless set).
- **`apollonia` CLI**: `db upgrade`, `ingest` (`--topic`, `--refresh`), `search` (`--k`,
  `--mode`) and `eval retrieval`. Exit codes: `0` success, `1` some articles failed to ingest,
  `2` invalid usage, `3` operational error. Operational errors are reported as one line without
  a traceback: database unreachable (the password is never printed), missing or invalid topics
  file or dataset, and the `embeddings` extra not installed. The database is checked before
  any slow work starts.
- **HTTP API** (FastAPI):
  - `GET /search` with `q`, `k` and `mode`; invalid input (empty or whitespace-only query,
    over-long query, out-of-range `k`, unknown mode) is rejected with `422`.
  - `GET /health` checks that the schema is in place, and reports `503` with
    `"status": "degraded"` when the database is unreachable or not migrated.
  - A database outage returns `503`; other database errors are logged and return a JSON `500`.
- **Retrieval evaluation**: a 50-question dataset and `apollonia eval retrieval`, which reports
  recall@1, recall@5 and MRR for each retrieval mode, lists the misses, and records the dataset
  hash, embedding model, chunking and search configuration and Apollonia version. Expected
  titles that are not in the knowledge base are reported, both in the report and as a warning.
- **Tooling**: `scripts/check.sh` quality gate (ruff, ruff format, mypy --strict, pytest),
  integration tests against PostgreSQL + pgvector via testcontainers, and a GitHub Actions
  workflow running the same gate on pushes to `main` and on every pull request.
- Architecture decision records 0001–0003 in `docs/adr/`.

[Unreleased]: https://github.com/rshehaj/apollonia/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rshehaj/apollonia/releases/tag/v0.1.0
