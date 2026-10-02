# Apollonia — guide for AI coding agents

Apollonia is an open-source AI tutor for the Albanian State Matura exam. It answers questions
in Albanian from openly licensed sources and cites the exact source revision it used.
The design lives in `docs/specs/`; architecture decisions live in `docs/adr/`.

## Ground rules

1. **The maintainer owns version control.** Never run `git` in any form, read-only commands
   included. Report the files you changed; the maintainer commits.
2. **Paid APIs need explicit approval.** Before any call to OpenAI, Anthropic or another paid
   service, stop and ask, with an estimated cost. Tests and CI use fakes (`FakeEmbedder`,
   fake LLM providers) and never call paid APIs.
3. **Test first.** Write the failing test, run it and see it fail, implement, then run it and
   see it pass.
4. **Quality gate.** `scripts/check.sh` (ruff, ruff format, mypy --strict, pytest) must pass
   before any work is reported as done.
5. **Follow the spec.** If the spec or plan is ambiguous or wrong, stop and ask rather than
   guess. Record significant design decisions as ADRs in `docs/adr/`.
6. **No redistributed source text.** Wikipedia content is fetched at run time into
   `backend/.cache/` and is never committed.
7. **Stay in scope.** Implement what the current task asks for; note follow-ups instead of
   building them.

## Layout

```
backend/            Python package `apollonia` (uv project)
  apollonia/        config, normalize, topics, embeddings, db/, ingest/, retrieval/,
                    evaluation/, api/, cli.py
  data/             topic map (syllabus topic → Wikipedia articles)
  evals/data/       evaluation datasets
  migrations/       Alembic migrations (the source of truth for the schema)
  tests/            pytest; `integration` marker = needs Docker
frontend/           Next.js app (from M2)
docs/specs/         design specifications
docs/adr/           architecture decision records
docs/evals/         generated evaluation reports
scripts/check.sh    quality gate (also used by CI)
```

## Conventions

- Python 3.12, `uv`, ruff (line length 100), `mypy --strict`, pytest.
- Small modules with one responsibility; pure functions for logic, thin CLI/API layers.
- Configuration comes only from `APOLLONIA_*` environment variables (`apollonia.config.Settings`).
- English for code and documentation; Albanian for tutor content and test fixtures.
- Suggested commit messages follow Conventional Commits.
- Public documentation is written for users and contributors of an open-source project.

## Commands

```bash
docker compose up -d db                 # local PostgreSQL + pgvector (port 5433)
cd backend && uv sync                   # dev environment (add --extra embeddings for bge-m3)
scripts/check.sh                        # full quality gate (from the repo root)
uv run pytest -m "not integration"      # fast tests without Docker
uv run apollonia --help                 # CLI
```

## Workflow

Milestones run through the `/milestone <id>` skill (`.claude/skills/milestone/SKILL.md`):
spec → maintainer approval → plan → maintainer approval → per task: `implementer` agent →
quality gate → `reviewer` agent → verification → final review → handoff to the maintainer.
