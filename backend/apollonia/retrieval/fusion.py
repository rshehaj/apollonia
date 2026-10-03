from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], k: int = 60
) -> list[tuple[int, float]]:
    """Fuse ranked id lists: ``score(d) = Σ 1 / (k + rank_i(d))``.

    Uses ranks only, so scores from different retrievers never need calibrating.
    Ties are broken by id to keep results deterministic.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
