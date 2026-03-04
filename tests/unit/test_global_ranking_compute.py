"""
Unit tests for assign_global_rankings (pure logic, no Firestore).
"""

from functions.scoring_triggers.global_ranking import assign_global_rankings


def test_three_users_ranked_by_pts_desc() -> None:
    result = assign_global_rankings([("u1", 2100), ("u2", 2500), ("u3", 1900)])
    assert result == [("u2", 1), ("u1", 2), ("u3", 3)]


def test_single_user_gets_rank_1() -> None:
    result = assign_global_rankings([("u1", 1500)])
    assert result == [("u1", 1)]


def test_empty_returns_empty() -> None:
    assert assign_global_rankings([]) == []


def test_equal_pts_assigns_sequential_ranks() -> None:
    # Stable sort: input order preserved among equal-pts users
    result = assign_global_rankings([("u1", 2000), ("u2", 2000)])
    ranks = [rank for _, rank in result]
    assert ranks == [1, 2]


def test_already_sorted_input_produces_same_order() -> None:
    result = assign_global_rankings([("u1", 3000), ("u2", 2000), ("u3", 1000)])
    assert result == [("u1", 1), ("u2", 2), ("u3", 3)]


def test_reverse_sorted_input_produces_correct_order() -> None:
    result = assign_global_rankings([("u3", 1000), ("u2", 2000), ("u1", 3000)])
    assert result == [("u1", 1), ("u2", 2), ("u3", 3)]
