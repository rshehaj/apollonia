import pytest

from apollonia.retrieval.fusion import reciprocal_rank_fusion


def test_items_ranked_high_in_both_lists_win() -> None:
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]], k=60)
    assert [item for item, _ in fused] == [1, 3, 2, 4]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_ties_are_broken_by_id() -> None:
    assert [item for item, _ in reciprocal_rank_fusion([[5], [4]])] == [4, 5]


def test_empty_rankings() -> None:
    assert reciprocal_rank_fusion([[], []]) == []
