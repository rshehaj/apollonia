# ADR 0003 — Hybrid retrieval with Reciprocal Rank Fusion

- **Status:** Accepted
- **Date:** 2026-10-02

## Context
Dense embeddings capture meaning but can miss exact names, dates and rare terms; keyword search
does the opposite. Students frequently type Albanian without diacritics ("Skenderbeu").

## Decision
Run vector search and accent-folded keyword search side by side, take the top 20 candidates of
each, and merge them with Reciprocal Rank Fusion (`k = 60`).

- Documents are indexed with the `simple` text-search configuration after `unaccent`.
- The query is accent-folded and lower-cased, stop words are removed, and the remaining terms
  are OR-combined (an AND query would almost never match a natural-language question).

## Consequences
- RRF uses ranks only, so the two retrievers' scores never need calibration.
- Accent folding makes typing without diacritics work for keyword matches.
- OR-combining favours recall; ranking (`ts_rank_cd`) and fusion restore precision.
- Without an Albanian stemmer, inflected forms ("Krujë" / "Krujën") only match through the vector
  side; the evaluation tracks whether this limits recall.

## Evaluation (2026-10-03)
First run on the real corpus (43 articles, 706 chunks), 50-question development set
([report](../evals/retrieval-2026-10-03.md)):

| Mode | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|
| vector | 0.94 | 1.00 | 0.97 |
| keyword | 0.76 | 0.94 | 0.84 |
| hybrid | 0.90 | 0.98 | 0.94 |

On this set, vector-only retrieval slightly outperforms the equal-weight fusion: `bge-m3` already
handles Albanian paraphrase and accent-less input well, and the keyword list occasionally lifts a
weaker passage (e.g. a "literature and art" section that mentions both query terms).

The hybrid default is kept for now, because the set is small, written as natural-language questions
(which favour dense retrieval), and has no held-out split. Fusion weighting will be re-evaluated on a
held-out set before answer generation depends on it.
