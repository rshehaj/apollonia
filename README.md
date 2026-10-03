# Apollonia

**An open-source AI tutor for the Albanian State Matura exam: grounded answers, cited sources.**

[![CI](https://github.com/rshehaj/apollonia/actions/workflows/ci.yml/badge.svg)](https://github.com/rshehaj/apollonia/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

> Named after Apollonia of Illyria, near present-day Fier, whose school the young Octavian
> (later Emperor Augustus) was attending in 44 BC.

Students ask questions in Albanian. Apollonia retrieves the relevant passages from openly licensed
sources and answers only from them, citing the exact source revision. The first subject is
**History**, built on a curated corpus of Albanian Wikipedia articles.

## Status

| Milestone | Status |
|---|---|
| M1 — Knowledge base: ingestion, hybrid search, retrieval evaluation | ✅ `v0.1.0` |
| M2 — Ask & learn: grounded, cited answers with streaming and answer evaluation | Planned |
| M3 — Practice quizzes | Planned |
| M4 — Open-answer checking | Planned |
| M5 — Progress tracking | Planned |

Progress is tracked in [issues and milestones](https://github.com/rshehaj/apollonia/milestones).

## How it works

```
topics.yaml ──▶ Wikipedia API ──▶ sections ──▶ chunks ──▶ bge-m3 ──▶ PostgreSQL
                (rate-limited,    (reference    (≤512        embeddings   pgvector HNSW
                 cached)           sections     tokens,                   + accent-folded
                                   removed)     overlap)                  full-text index

question ──▶ vector search ─┐
         └─▶ keyword search ─┴─▶ Reciprocal Rank Fusion ──▶ top-k passages + revision links
```

- **Hybrid retrieval.** Dense `bge-m3` vectors capture meaning, and full-text search catches names
  and dates. The two are fused with Reciprocal Rank Fusion. See
  [ADR 0003](docs/adr/0003-hybrid-retrieval-rrf.md).
- **Built for how students type.** Accent folding means "Skenderbeu" finds "Skënderbeu", and Albanian
  stop words are removed from keyword queries.
- **Reproducible citations.** Every passage links to the exact Wikipedia revision it came from.
- **Safe to re-run.** Ingestion only re-embeds changed articles. One failing article never aborts a
  run, and stale documents are pruned only after a fully successful run.
- **Measured, not assumed.** A labeled Albanian evaluation set tracks retrieval quality per strategy.

## Evaluation

Retrieval over 50 labeled Albanian questions on the full History corpus (43 articles, 706 chunks),
[full report](docs/evals/retrieval-2026-10-03.md):

| Mode | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|
| vector | 0.94 | 1.00 | 0.97 |
| keyword | 0.76 | 0.94 | 0.84 |
| hybrid | 0.90 | 0.98 | 0.94 |

Every question finds its source article within the top 10 in all three modes. On this development
set, vector-only retrieval edges out the equal-weight fusion. The analysis and next steps are in
[ADR 0003](docs/adr/0003-hybrid-retrieval-rrf.md). These are development-set numbers; a held-out
split is planned before answer generation is tuned.

## Quickstart

Requirements: Docker, [uv](https://docs.astral.sh/uv/), and about 6 GB of disk (CPU PyTorch is ~1.1 GB;
the `bge-m3` model cache is ~4.5 GB).

```bash
docker compose up -d db
cd backend
cp .env.example .env          # set APOLLONIA_WIKIPEDIA_USER_AGENT to include your contact
uv sync --extra embeddings
uv run apollonia db upgrade
uv run apollonia ingest       # ~7 minutes on a laptop CPU
uv run apollonia search "Kur u themelua Lidhja e Prizrenit?"
uv run apollonia eval retrieval
```

Re-running `apollonia ingest` reuses the local Wikipedia cache. Use `apollonia ingest --refresh` to
pick up new article revisions; only changed articles are re-embedded. Once the model is cached,
set `HF_HUB_OFFLINE=1` to skip Hugging Face Hub checks and run fully offline.

HTTP API (interactive docs at `http://localhost:8000/docs`):

```bash
uv run uvicorn apollonia.api.app:create_app --factory --port 8000
curl "http://localhost:8000/search?q=Sk%C3%ABnderbeu%20Kruj%C3%AB&k=3"
```

| Endpoint | Description |
|---|---|
| `GET /search?q=&k=&mode=` | Ranked passages (`hybrid`, `vector` or `keyword`) with revision permalinks |
| `GET /health` | Database and schema readiness (`503` when degraded) |

CLI exit codes: `0` success · `1` some articles failed · `2` usage error · `3` operational error
(for example, the database is unreachable).

## Development

```bash
cd backend
uv sync
cd .. && scripts/check.sh   # ruff, ruff format, mypy --strict, pytest (Docker needed for integration tests)
```

Tests use a deterministic fake embedder and a real PostgreSQL with pgvector, started through
testcontainers. No paid APIs are called in tests or CI.

Design: [specification](docs/specs/2026-10-02-apollonia-design.md) ·
[architecture decisions](docs/adr/) · [changelog](CHANGELOG.md)

## Data and licensing

Code is released under the [MIT License](LICENSE). Source text is retrieved at run time from
[Albanian Wikipedia](https://sq.wikipedia.org) under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) and is not redistributed in this
repository; every result links to its source revision. Evaluation datasets are released under
CC BY-SA 4.0.
