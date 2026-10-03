# Apollonia — Design Specification

**Status:** Draft for review
**Date:** 2026-10-02
**Scope:** Overall architecture, milestone roadmap, and detailed design for M1 (Knowledge base) and M2 (Ask & learn + evaluation). M3–M5 are outlined and receive their own specs when started.

---

## 1. Overview

Apollonia is an open-source AI tutor for the Albanian State Matura exam (*Provimi i Maturës Shtetërore*). Students ask questions and practice in Albanian; every answer is grounded in openly licensed sources and cites the passage it relies on.

The first subject is **History** (*Histori*), backed by a curated corpus of Albanian Wikipedia articles. Further subjects (Biology, Mathematics, …) follow the same pipeline once the History vertical is complete.

The project is named after Apollonia of Illyria, an ancient city near present-day Fier whose school counted the young Octavian (later Emperor Augustus) among its students.

### 1.1 Goals

- Grounded answers in Albanian with verifiable citations to specific source revisions.
- Honest abstention: the tutor says it cannot find an answer rather than guessing.
- Quality is measured, not assumed: retrieval and answer quality are tracked by a reproducible evaluation suite.
- Provider-agnostic LLM layer; runs end to end with an OpenAI key, with Anthropic as an optional provider.
- Easy to run locally (`docker compose up`) and easy to integrate into other products via a JSON API.

### 1.2 Non-goals (for M1–M2)

- Multi-turn conversations with follow-up rewriting (planned after M2).
- User accounts and personalization (M5).
- Subjects other than History.
- Redistributing source text inside the repository.

---

## 2. Milestone roadmap

Each milestone is independently shippable and tagged as a release.

| Milestone | Release | Delivers |
|---|---|---|
| M1 — Knowledge base | `v0.1.0` | Wikipedia ingestion, chunking, embeddings, hybrid search, retrieval evaluation |
| M2 — Ask & learn | `v0.2.0` | Grounded answers with citations, abstention, SSE streaming, answer evaluation suite, chat UI |
| M3 — Practice quiz | `v0.3.0` | Matura-style multiple-choice questions tied to source passages, with automatic quality filtering |
| M4 — Answer checking | `v0.4.0` | Rubric-based grading of open answers with structured feedback; judge calibrated against human grades |
| M5 — Progress tracking | `v0.5.0` | Accounts, attempt history, per-topic mastery, study recommendations |

---

## 3. Architecture

### 3.1 Components

```
┌──────────────┐  REST + SSE   ┌──────────────────────────────┐
│  Next.js UI  │ ────────────▶ │  FastAPI backend             │
│ (TypeScript) │               │  ├─ api/        routes, SSE  │
└──────────────┘               │  ├─ tutor/      ask/quiz/grade│──▶ LLM provider
                               │  ├─ retrieval/  hybrid search│     (OpenAI | Anthropic)
                               │  ├─ ingest/     pipeline     │──▶ Wikipedia API
                               │  └─ llm/        providers    │
                               └──────────────┬───────────────┘
                                              │
                                   ┌──────────▼──────────┐
                                   │ PostgreSQL 16       │
                                   │ + pgvector, unaccent│
                                   └─────────────────────┘
```

- **Frontend** talks only to the backend. API keys never reach the browser.
- **Backend** owns all LLM, embedding, and database access.
- **PostgreSQL** stores documents, chunks, vectors (pgvector), the full-text index, and (from M5) user data. A single datastore keeps operations simple at this scale; ADR-0001 records the trade-off against a dedicated vector database.

### 3.2 Repository layout

```
apollonia/
├── backend/
│   ├── apollonia/
│   │   ├── config.py          settings via pydantic-settings (env vars)
│   │   ├── db/                SQLAlchemy models, sessions, programmatic migrate
│   │   ├── ingest/            fetch, clean, chunk, embed
│   │   ├── retrieval/         vector, keyword, fusion
│   │   ├── llm/               provider interface + implementations
│   │   ├── tutor/             ask (M2), quiz (M3), grade (M4)
│   │   ├── progress/          (M5)
│   │   ├── evaluation/        eval metrics, runners, reports
│   │   ├── api/               FastAPI app and routers
│   │   └── cli.py             Typer CLI
│   ├── data/topics.yaml       syllabus topic → article titles
│   ├── migrations/            Alembic migrations (source of truth for the schema)
│   ├── evals/data/            evaluation datasets
│   ├── tests/
│   └── pyproject.toml         managed with uv
├── frontend/                  Next.js (App Router), TypeScript, Tailwind
├── docs/
│   ├── adr/                   architecture decision records
│   ├── evals/                 generated evaluation reports
│   └── specs/                 design specifications
├── docker-compose.yml
├── .github/workflows/
├── CHANGELOG.md
├── LICENSE                    MIT (code)
└── README.md
```

### 3.3 Technology choices

| Concern | Choice |
|---|---|
| Language / packaging | Python 3.12, `uv` |
| API | FastAPI, Server-Sent Events for streaming |
| Database | PostgreSQL 16 with `pgvector` and `unaccent` extensions |
| ORM / migrations | SQLAlchemy 2.x, Alembic, `psycopg` 3 |
| Embeddings | `BAAI/bge-m3` via `sentence-transformers`, CPU inference, 1024 dimensions |
| LLM | `openai` SDK (default), `anthropic` SDK (optional extra) |
| CLI | Typer |
| HTTP client | `httpx` |
| Frontend | Next.js (App Router), TypeScript, Tailwind CSS |
| Quality | `ruff`, `mypy --strict`, `pytest`; ESLint, `tsc`, Playwright |

---

## 4. Licensing and attribution

- **Code** is MIT-licensed.
- **Source text** comes from Albanian Wikipedia under CC BY-SA 4.0. The repository does **not** contain article text; it ships the ingestion pipeline, which downloads articles at run time.
- **Evaluation datasets** contain original questions and short expected facts; they are published under CC BY-SA 4.0 to stay compatible with the sources they reference.
- Every answer shown to a user links to the exact Wikipedia revision it cites. The README carries an attribution notice.

---

## 5. M1 — Knowledge base

### 5.1 Topic map

`backend/data/topics.yaml` maps Matura History syllabus topics to Albanian Wikipedia article titles:

```yaml
- id: rilindja-kombetare
  name: Rilindja Kombëtare
  articles:
    - Rilindja Kombëtare
    - Lidhja e Prizrenit
    - Kongresi i Manastirit
```

Topic IDs are stable identifiers reused by the quiz (M3) and progress tracking (M5). An article may belong to more than one topic.

### 5.2 Fetching

- Source: MediaWiki Action API on `sq.wikipedia.org`.
- For each title, fetch the current revision ID and the article's plain text with section structure.
- Requests send a descriptive `User-Agent` with a contact URL, are rate-limited (max 1 request/second by default), and are cached on disk under `backend/.cache/` (not committed).
- Redirects are resolved; missing titles are reported and skipped, not fatal.

### 5.3 Cleaning

- Remove reference and navigation sections — *Referime*, *Shënime*, *Shih edhe* / *Shiko edhe*, *Lidhje të jashtme*, *Bibliografia*, *Literatura*, *Burime*, *Galeria* — together with their subsections (matched case- and accent-insensitively).
- Strip residual markup, citation markers, and empty sections.
- Normalize Unicode to NFC and collapse whitespace.

### 5.4 Chunking

- Section-aware: chunks never cross a section boundary (at any heading level).
- Target size 400 tokens, maximum 512, overlap 50 tokens, measured with the embedding model's tokenizer.
- Each chunk's embedded text is prefixed with its heading path, e.g. `Lidhja e Prizrenit > Rezistenca e armatosur`.
- Stored metadata: article title, section path, URL, revision ID, topic IDs, chunk ordinal, content hash.

### 5.5 Storage

| Table | Key columns |
|---|---|
| `documents` | `id`, `title`, `url`, `revision_id`, `content_hash`, `fetched_at` |
| `chunks` | `id`, `document_id`, `ordinal`, `section_path`, `text`, `embedding vector(1024)`, `tsv tsvector`, `content_hash` |
| `document_topics` | `document_id`, `topic_id` |

- `tsv` is generated from `unaccent(section_path || ' ' || text)` with the `simple` text-search configuration (Postgres has no Albanian stemmer). A GIN index serves keyword search.
- An HNSW index on `embedding` (cosine distance) serves vector search.
- Re-ingestion is idempotent: a document whose revision ID and content hash are unchanged is skipped; a changed document has its chunks replaced in a single transaction.

### 5.6 Hybrid retrieval

1. **Vector search:** embed the query with `bge-m3`, take the top 20 by cosine similarity.
2. **Keyword search:** the query is accent-folded, tokenized, and stripped of Albanian stop words; the remaining terms are OR-combined into a `to_tsquery('simple', …)` (an AND query would almost never match a natural-language question). Top 20 by `ts_rank_cd`.
3. **Fusion:** Reciprocal Rank Fusion, `score = Σ 1 / (60 + rank)`, across both lists.
4. Return the top *k* fused chunks (default *k* = 6) with their scores and metadata.

Accent folding via `unaccent` means queries such as "Skenderbeu" match "Skënderbeu", which matters because students frequently type without ë and ç.

### 5.7 Retrieval evaluation

- Dataset `backend/evals/data/retrieval.yaml`: about 50 Albanian questions, each labeled with the article that answers it (optionally narrowed to a section). A question counts as a hit at rank *r* if the result at rank *r* matches any of its labels.
- Metrics: **recall@1**, **recall@5** and **MRR@10**, computed for vector-only, keyword-only, and hybrid retrieval.
- `apollonia eval retrieval` writes a Markdown report to `docs/evals/`.

### 5.8 Interfaces

- CLI: `apollonia db upgrade`, `apollonia ingest [--topic ID] [--refresh]`, `apollonia search "query" [--k N] [--mode hybrid|vector|keyword]`, `apollonia eval retrieval [--dataset] [--output] [--depth]`. Exit codes: 0 success, 1 some articles failed, 2 usage error, 3 operational error.
- API: `GET /search?q=…&k=…&mode=…` → `{query, mode, results}`, where each result has chunk id, title, section path, text, URL, revision permalink, revision ID, score and vector similarity (null for keyword-only hits).

---

## 6. M2 — Ask & learn

### 6.1 LLM provider interface

```python
class LLMProvider(Protocol):
    def stream(self, messages: list[Message]) -> AsyncIterator[StreamEvent]: ...
    async def structured(self, messages: list[Message], schema: type[T]) -> T: ...
```

- `StreamEvent` carries either a text delta or final usage (input/output tokens).
- Implementations: `OpenAIProvider` (default), `AnthropicProvider` (installed via the `anthropic` extra), `FakeProvider` (deterministic, used in tests and CI).
- Provider and model names are selected by environment variables (`APOLLONIA_LLM_PROVIDER`, `APOLLONIA_LLM_MODEL`); no model name is hard-coded in application logic.

### 6.2 Ask pipeline

1. Retrieve top *k* chunks (§5.6).
2. **Relevance gate:** if the highest cosine similarity among the vector-search results is below `APOLLONIA_MIN_RELEVANCE`, return the abstention message *"Nuk e gjej këtë në burimet e mia."* without calling the LLM. The default threshold is chosen in M2 by sweeping candidate values on the evaluation set and selecting the one that maximizes abstention accuracy without lowering answerable-question correctness; the chosen value and the sweep are recorded in an ADR.
3. **Prompt:** a system prompt (in Albanian) instructs the model to answer only from the provided sources, cite each claim with `[n]`, abstain with the fixed message when the sources are insufficient, and treat source content as data rather than instructions. Sources are passed as numbered, clearly delimited blocks.
4. **Stream** the answer.
5. **Citation validation:** markers referring to sources that were not provided are removed and logged.

### 6.3 Streaming API

`POST /ask` with body `{"question": "…"}` returns `text/event-stream`:

| Event | Payload |
|---|---|
| `sources` | list of the chunks provided to the model (index, title, section path, URL with `oldid`, excerpt) — sent first |
| `token` | text delta |
| `done` | `{abstained, input_tokens, output_tokens, est_cost_usd, latency_ms}` |
| `error` | `{code, message}` |

### 6.4 Frontend

- Chat view with streamed answer text.
- Citation markers render as chips linking to the cited Wikipedia revision.
- A side panel shows the source passages used for the answer.

### 6.5 Observability

One structured (JSON) log line per request: request ID, retrieved chunk IDs, provider, model, token counts, estimated cost, latency, abstention flag. Per-model prices live in configuration.

### 6.6 Answer evaluation

- Dataset `backend/evals/data/answers.yaml`: about 60 questions — about 45 answerable, each with a list of expected key facts, and about 15 unanswerable (outside the corpus or off-topic).
- Metrics:
  - **Citation validity** — deterministic: every marker refers to a provided source.
  - **Abstention accuracy** — abstains on unanswerable, answers answerable.
  - **Correctness** — LLM judge: proportion of expected key facts present.
  - **Faithfulness** — LLM judge: proportion of claims supported by the cited passage.
  - **Latency** (p50/p95) and **cost** per question.
- `apollonia eval answers` writes a Markdown report to `docs/evals/`; the README shows the latest summary.

---

## 7. Error handling

- **Wikipedia unavailable / rate-limited:** retry with exponential backoff (3 attempts), then skip the article and report it in the ingest summary.
- **LLM provider error or timeout:** emit an `error` SSE event with a stable code (`llm_unavailable`, `llm_timeout`); no partial answer is presented as complete.
- **Empty or low-relevance retrieval:** abstain (§6.2), not an error.
- **Database unavailable:** API returns HTTP 503 with a JSON error body; health endpoint `GET /health` reports database and model readiness.

---

## 8. Testing and CI

- **Unit tests:** cleaning, chunking boundaries and sizes, accent normalization, RRF fusion, citation validation, SSE event formatting.
- **Integration tests:** PostgreSQL with pgvector started per test session via testcontainers (locally and in CI), with fake embedding and LLM providers, covering ingest → search → ask on a small fixture corpus.
- **Frontend:** ESLint, `tsc`, production build; a Playwright smoke test once the chat UI exists.
- **CI (GitHub Actions)**, on pushes to `main` and on every pull request: `ruff`, `mypy --strict`, `pytest`, frontend lint/type-check/build. No paid API calls.
- **Paid evaluations** run only via a manually triggered workflow using a repository secret.

## 9. Project conventions

- Conventional Commits; `CHANGELOG.md` updated per release.
- One release tag per milestone (§2).
- Architecture Decision Records in `docs/adr/`, starting with: 0001 PostgreSQL + pgvector, 0002 `bge-m3` embeddings, 0003 hybrid retrieval with RRF, 0004 provider-agnostic LLM interface.
- README: pitch, demo, architecture diagram, evaluation results, quickstart, roadmap, attribution.

---

## 10. Future milestones (outline)

- **M3 — Practice quiz:** structured generation of a question, four options, the correct index, an explanation, and the source chunk ID. An automatic validator rejects items whose answer is not supported by the source, that have duplicate or trivially wrong options, or that leak the answer in the stem. Accepted items are cached and tagged by topic.
- **M4 — Answer checking:** rubric-based grading returning structured feedback (correct points, missing points, incorrect claims, score). The judge is calibrated against roughly 30 human-graded answers and its agreement rate is reported.
- **M5 — Progress tracking:** accounts, attempt history, per-topic mastery scores, and recommendations of topics to study next.
