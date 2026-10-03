# ADR 0001 — PostgreSQL with pgvector as the single datastore

- **Status:** Accepted
- **Date:** 2026-10-02

## Context
Apollonia needs vector similarity search, keyword search and, from M5, relational user data.
The History corpus is a few thousand chunks; future subjects stay within the low millions.

## Decision
Use PostgreSQL 16 with the `pgvector` extension (HNSW, cosine distance) for vectors and the
built-in full-text search for keywords. No dedicated vector database.

## Consequences
- One system to run, back up and reason about; transactions and joins span vectors and user data.
- Hybrid search runs entirely in SQL.
- HNSW is approximate: a query returns at most `hnsw.ef_search` candidates (default 40). The
  current pool of 20 candidates per retriever fits within that; if candidate pools grow, raise
  `ef_search` for those queries.
- At much larger scale or with strict latency targets, a dedicated vector store may be revisited;
  the retrieval module isolates that change.
