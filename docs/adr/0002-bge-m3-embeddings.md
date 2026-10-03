# ADR 0002 — `BAAI/bge-m3` for embeddings

- **Status:** Accepted
- **Date:** 2026-10-02

## Context
The corpus and the questions are in Albanian, a lower-resource language. Embedding every chunk and
every query through a paid API adds per-request cost and an external dependency.

## Decision
Use `BAAI/bge-m3` (multilingual, 1024 dimensions, open weights) via sentence-transformers on CPU.
Chunk sizes are measured with the same model's tokenizer.

## Consequences
- No per-query embedding cost. The first run downloads the model into the Hugging Face cache
  (about 4.5 GB on disk, because the weights are downloaded in more than one format); after that
  the model loads from the local cache and works offline.
- Indexing on CPU takes minutes for the History corpus, which is acceptable for batch ingestion.
- The `Embedder` protocol allows swapping in a hosted model; the retrieval evaluation is the
  arbiter of any such change.
