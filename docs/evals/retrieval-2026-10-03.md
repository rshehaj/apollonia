# Retrieval evaluation — 2026-10-03

| Setting | Value |
|---|---|
| Dataset | `retrieval.yaml` (50 questions), sha256 `b854d6549e1c` |
| Corpus | 43 documents, 706 chunks |
| Embedding model | `BAAI/bge-m3` |
| Search depth | top 10 |
| Search candidates | 20 |
| Chunking | target 400, max 512, overlap 50 tokens |
| Apollonia version | `0.1.0` |

## Results

| Mode | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|
| vector | 0.94 | 1.00 | 0.97 |
| keyword | 0.76 | 0.94 | 0.84 |
| hybrid | 0.90 | 0.98 | 0.94 |

_Development set: the same questions are used for tuning, so these numbers are optimistic._

## Misses (hybrid, not in top 10)

None.
