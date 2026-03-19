"""Unit tests for the D7 tier averages computation (pure function)."""

from __future__ import annotations

from functions.scoring_triggers.tier_averages import compute_tier_averages_from_users


def _make_user(
    uid: str,
    sport: str,
    tier: str,
    axes: dict[str, int],
) -> dict:
    """Build a minimal Firestore-shaped user dict with ranking + skillDna for one sport."""
    dna_axes = {
        axis: {"positive": 5, "negative": 2, "score": score}
        for axis, score in axes.items()
    }
    dna_axes["totalReflections"] = 3
    return {
        "uid": uid,
        "rankings": {sport: {"sport": sport, "pts": 1000, "tier": tier}},
        "skillDna": {sport: dna_axes},
    }


# ---------------------------------------------------------------------------
# Basic averaging
# ---------------------------------------------------------------------------


def test_single_user_averages_equal_own_scores() -> None:
    user = _make_user("u1", "tennis", "amateur", {"serve": 60, "power": 40})
    result = compute_tier_averages_from_users([user])
    assert result == {"amateur": {"tennis": {"serve": 60, "power": 40}}}


def test_two_users_same_tier_same_sport() -> None:
    u1 = _make_user("u1", "tennis", "amateur", {"serve": 60, "power": 40})
    u2 = _make_user("u2", "tennis", "amateur", {"serve": 80, "power": 50})
    result = compute_tier_averages_from_users([u1, u2])
    assert result["amateur"]["tennis"]["serve"] == 70
    assert result["amateur"]["tennis"]["power"] == 45


def test_rounding() -> None:
    u1 = _make_user("u1", "padel", "intermediate", {"serve": 33})
    u2 = _make_user("u2", "padel", "intermediate", {"serve": 34})
    result = compute_tier_averages_from_users([u1, u2])
    # (33 + 34) / 2 = 33.5 -> rounds to 34
    assert result["intermediate"]["padel"]["serve"] == 34


# ---------------------------------------------------------------------------
# Multiple tiers / sports
# ---------------------------------------------------------------------------


def test_multiple_tiers() -> None:
    u1 = _make_user("u1", "tennis", "amateur", {"serve": 40})
    u2 = _make_user("u2", "tennis", "advanced", {"serve": 80})
    result = compute_tier_averages_from_users([u1, u2])
    assert result["amateur"]["tennis"]["serve"] == 40
    assert result["advanced"]["tennis"]["serve"] == 80


def test_multiple_sports_same_tier() -> None:
    u1 = _make_user("u1", "tennis", "amateur", {"mental": 50})
    u2 = _make_user("u2", "padel", "amateur", {"mental": 70})
    result = compute_tier_averages_from_users([u1, u2])
    assert result["amateur"]["tennis"]["mental"] == 50
    assert result["amateur"]["padel"]["mental"] == 70


def test_user_with_multiple_sports() -> None:
    user = {
        "uid": "u1",
        "rankings": {
            "tennis": {"sport": "tennis", "pts": 1000, "tier": "amateur"},
            "padel": {"sport": "padel", "pts": 2000, "tier": "intermediate"},
        },
        "skillDna": {
            "tennis": {
                "serve": {"positive": 5, "negative": 2, "score": 40},
                "totalReflections": 3,
            },
            "padel": {
                "serve": {"positive": 5, "negative": 2, "score": 60},
                "totalReflections": 3,
            },
        },
    }
    result = compute_tier_averages_from_users([user])
    assert result["amateur"]["tennis"]["serve"] == 40
    assert result["intermediate"]["padel"]["serve"] == 60


# ---------------------------------------------------------------------------
# Edge cases: skip logic
# ---------------------------------------------------------------------------


def test_empty_user_list() -> None:
    result = compute_tier_averages_from_users([])
    assert result == {}


def test_user_without_skill_dna_is_skipped() -> None:
    user = {
        "uid": "u1",
        "rankings": {"tennis": {"sport": "tennis", "pts": 1000, "tier": "amateur"}},
        "skillDna": None,
    }
    result = compute_tier_averages_from_users([user])
    assert result == {}


def test_user_without_rankings_is_skipped() -> None:
    user = {
        "uid": "u1",
        "rankings": None,
        "skillDna": {
            "tennis": {
                "serve": {"positive": 5, "negative": 2, "score": 50},
                "totalReflections": 3,
            }
        },
    }
    result = compute_tier_averages_from_users([user])
    assert result == {}


def test_user_with_missing_tier_is_skipped() -> None:
    user = {
        "uid": "u1",
        "rankings": {"tennis": {"sport": "tennis", "pts": 1000, "tier": None}},
        "skillDna": {
            "tennis": {
                "serve": {"positive": 5, "negative": 2, "score": 50},
                "totalReflections": 3,
            }
        },
    }
    result = compute_tier_averages_from_users([user])
    assert result == {}


def test_user_with_unknown_tier_is_skipped() -> None:
    user = {
        "uid": "u1",
        "rankings": {"tennis": {"sport": "tennis", "pts": 1000, "tier": "mythical"}},
        "skillDna": {
            "tennis": {
                "serve": {"positive": 5, "negative": 2, "score": 50},
                "totalReflections": 3,
            }
        },
    }
    result = compute_tier_averages_from_users([user])
    assert result == {}


def test_axis_with_no_score_key_is_skipped() -> None:
    user = {
        "uid": "u1",
        "rankings": {"tennis": {"sport": "tennis", "pts": 1000, "tier": "amateur"}},
        "skillDna": {
            "tennis": {
                "serve": {"positive": 5, "negative": 2},  # no "score" key
                "totalReflections": 3,
            }
        },
    }
    result = compute_tier_averages_from_users([user])
    assert result == {}


def test_sport_with_dna_but_no_ranking_is_skipped() -> None:
    user = {
        "uid": "u1",
        "rankings": {"tennis": {"sport": "tennis", "pts": 1000, "tier": "amateur"}},
        "skillDna": {
            "padel": {
                "serve": {"positive": 5, "negative": 2, "score": 50},
                "totalReflections": 3,
            }
        },
    }
    result = compute_tier_averages_from_users([user])
    assert result == {}


# ---------------------------------------------------------------------------
# All five axes present
# ---------------------------------------------------------------------------


def test_all_axes_averaged() -> None:
    axes = {"serve": 10, "power": 20, "net_play": 30, "stamina": 40, "mental": 50}
    u1 = _make_user("u1", "tennis", "amateur", axes)
    axes2 = {"serve": 30, "power": 40, "net_play": 50, "stamina": 60, "mental": 70}
    u2 = _make_user("u2", "tennis", "amateur", axes2)
    result = compute_tier_averages_from_users([u1, u2])
    expected = {"serve": 20, "power": 30, "net_play": 40, "stamina": 50, "mental": 60}
    assert result["amateur"]["tennis"] == expected
