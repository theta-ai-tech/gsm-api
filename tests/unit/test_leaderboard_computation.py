"""Unit tests for the D7 leaderboard computation (pure functions)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from functions.scheduled.leaderboard_computation import (
    build_area_to_region,
    build_leaderboard_entries,
    build_rising_stars,
    compute_delta7d_from_history,
    extract_users_by_region_sport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)


def _make_user(
    uid: str,
    name: str,
    area: int,
    sports: dict[str, int],
    tiers: dict[str, str] | None = None,
) -> dict:
    """Build a minimal Firestore-shaped user dict."""
    rankings = {}
    for sport, pts in sports.items():
        ranking: dict = {"sport": sport, "pts": pts}
        if tiers and sport in tiers:
            ranking["tier"] = tiers[sport]
        rankings[sport] = ranking
    return {
        "uid": uid,
        "name": name,
        "preferences": {"area": area},
        "rankings": rankings,
    }


# ---------------------------------------------------------------------------
# build_area_to_region
# ---------------------------------------------------------------------------


class TestBuildAreaToRegion:
    def test_basic_mapping(self) -> None:
        mapping = {"101": "athens", "202": "thessaloniki"}
        result = build_area_to_region(mapping)
        assert result == {101: "athens", 202: "thessaloniki"}

    def test_non_numeric_keys_skipped(self) -> None:
        mapping = {"abc": "london", "101": "athens"}
        result = build_area_to_region(mapping)
        assert result == {101: "athens"}

    def test_empty_mapping(self) -> None:
        assert build_area_to_region({}) == {}


# ---------------------------------------------------------------------------
# extract_users_by_region_sport
# ---------------------------------------------------------------------------


class TestExtractUsersByRegionSport:
    def test_single_user_single_sport(self) -> None:
        area_to_region = {101: "athens"}
        users = [_make_user("u1", "Alice", 101, {"tennis": 800})]
        buckets = extract_users_by_region_sport(users, area_to_region)
        assert ("athens", "tennis") in buckets
        assert len(buckets[("athens", "tennis")]) == 1

    def test_user_with_multiple_sports(self) -> None:
        area_to_region = {101: "athens"}
        users = [_make_user("u1", "Alice", 101, {"tennis": 800, "padel": 600})]
        buckets = extract_users_by_region_sport(users, area_to_region)
        assert ("athens", "tennis") in buckets
        assert ("athens", "padel") in buckets

    def test_user_without_area_skipped(self) -> None:
        area_to_region = {101: "athens"}
        user = {
            "uid": "u1",
            "name": "Bob",
            "preferences": {},
            "rankings": {"tennis": {"sport": "tennis", "pts": 500}},
        }
        buckets = extract_users_by_region_sport([user], area_to_region)
        assert len(buckets) == 0

    def test_user_with_unknown_area_skipped(self) -> None:
        area_to_region = {101: "athens"}
        users = [_make_user("u1", "Alice", 999, {"tennis": 800})]
        buckets = extract_users_by_region_sport(users, area_to_region)
        assert len(buckets) == 0

    def test_user_without_rankings_skipped(self) -> None:
        area_to_region = {101: "athens"}
        user = {
            "uid": "u1",
            "name": "Bob",
            "preferences": {"area": 101},
            "rankings": None,
        }
        buckets = extract_users_by_region_sport([user], area_to_region)
        assert len(buckets) == 0

    def test_multiple_users_same_region(self) -> None:
        area_to_region = {101: "athens", 102: "athens"}
        users = [
            _make_user("u1", "Alice", 101, {"tennis": 800}),
            _make_user("u2", "Bob", 102, {"tennis": 600}),
        ]
        buckets = extract_users_by_region_sport(users, area_to_region)
        assert len(buckets[("athens", "tennis")]) == 2

    def test_empty_users(self) -> None:
        area_to_region = {101: "athens"}
        buckets = extract_users_by_region_sport([], area_to_region)
        assert len(buckets) == 0


# ---------------------------------------------------------------------------
# build_leaderboard_entries
# ---------------------------------------------------------------------------


class TestBuildLeaderboardEntries:
    def test_sorts_by_pts_desc(self) -> None:
        users = [
            _make_user("u1", "Alice", 101, {"tennis": 500}),
            _make_user("u2", "Bob", 101, {"tennis": 800}),
            _make_user("u3", "Carol", 101, {"tennis": 600}),
        ]
        delta7d_map: dict[str, int] = {}
        entries = build_leaderboard_entries(users, "tennis", delta7d_map)
        assert entries[0]["uid"] == "u2"
        assert entries[0]["pts"] == 800
        assert entries[0]["rank"] == 1
        assert entries[1]["uid"] == "u3"
        assert entries[1]["rank"] == 2
        assert entries[2]["uid"] == "u1"
        assert entries[2]["rank"] == 3

    def test_respects_top_n(self) -> None:
        users = [
            _make_user(f"u{i}", f"User{i}", 101, {"tennis": i * 100}) for i in range(15)
        ]
        entries = build_leaderboard_entries(users, "tennis", {}, top_n=10)
        assert len(entries) == 10
        assert entries[0]["pts"] == 1400

    def test_includes_delta7d(self) -> None:
        users = [_make_user("u1", "Alice", 101, {"tennis": 800})]
        delta7d_map = {"u1": 45}
        entries = build_leaderboard_entries(users, "tennis", delta7d_map)
        assert entries[0]["delta7d"] == 45

    def test_includes_tier_when_present(self) -> None:
        users = [
            _make_user("u1", "Alice", 101, {"tennis": 800}, tiers={"tennis": "amateur"})
        ]
        entries = build_leaderboard_entries(users, "tennis", {})
        assert entries[0]["tier"] == "amateur"

    def test_omits_tier_when_absent(self) -> None:
        users = [_make_user("u1", "Alice", 101, {"tennis": 800})]
        entries = build_leaderboard_entries(users, "tennis", {})
        assert "tier" not in entries[0]

    def test_empty_users(self) -> None:
        entries = build_leaderboard_entries([], "tennis", {})
        assert entries == []

    def test_user_without_pts_for_sport_skipped(self) -> None:
        user = {
            "uid": "u1",
            "name": "Alice",
            "preferences": {"area": 101},
            "rankings": {"tennis": {"sport": "tennis"}},
        }
        entries = build_leaderboard_entries([user], "tennis", {})
        assert entries == []


# ---------------------------------------------------------------------------
# build_rising_stars
# ---------------------------------------------------------------------------


class TestBuildRisingStars:
    def test_sorts_by_delta7d_desc(self) -> None:
        users = [
            _make_user("u1", "Alice", 101, {"tennis": 500}),
            _make_user("u2", "Bob", 101, {"tennis": 800}),
            _make_user("u3", "Carol", 101, {"tennis": 600}),
        ]
        delta7d_map = {"u1": 50, "u2": 30, "u3": 80}
        stars = build_rising_stars(users, "tennis", delta7d_map)
        assert stars[0]["uid"] == "u3"
        assert stars[0]["delta7d"] == 80
        assert stars[0]["rank"] == 1
        assert stars[1]["uid"] == "u1"
        assert stars[2]["uid"] == "u2"

    def test_excludes_zero_or_negative_delta(self) -> None:
        users = [
            _make_user("u1", "Alice", 101, {"tennis": 500}),
            _make_user("u2", "Bob", 101, {"tennis": 800}),
        ]
        delta7d_map = {"u1": 0, "u2": -10}
        stars = build_rising_stars(users, "tennis", delta7d_map)
        assert stars == []

    def test_respects_top_n(self) -> None:
        users = [
            _make_user(f"u{i}", f"User{i}", 101, {"tennis": i * 100}) for i in range(10)
        ]
        delta7d_map = {f"u{i}": (i + 1) * 10 for i in range(10)}
        stars = build_rising_stars(users, "tennis", delta7d_map, top_n=5)
        assert len(stars) == 5
        assert stars[0]["delta7d"] == 100

    def test_empty_users(self) -> None:
        stars = build_rising_stars([], "tennis", {})
        assert stars == []

    def test_includes_pts(self) -> None:
        users = [_make_user("u1", "Alice", 101, {"tennis": 750})]
        delta7d_map = {"u1": 25}
        stars = build_rising_stars(users, "tennis", delta7d_map)
        assert stars[0]["pts"] == 750


# ---------------------------------------------------------------------------
# compute_delta7d_from_history
# ---------------------------------------------------------------------------


class TestComputeDelta7dFromHistory:
    def test_sums_recent_deltas(self) -> None:
        entries = [
            {"delta": 30, "createdAt": _NOW - timedelta(days=1)},
            {"delta": -10, "createdAt": _NOW - timedelta(days=3)},
            {"delta": 20, "createdAt": _NOW - timedelta(days=6)},
        ]
        assert compute_delta7d_from_history(entries, _NOW) == 40

    def test_excludes_old_entries(self) -> None:
        entries = [
            {"delta": 30, "createdAt": _NOW - timedelta(days=1)},
            {"delta": 50, "createdAt": _NOW - timedelta(days=8)},
        ]
        assert compute_delta7d_from_history(entries, _NOW) == 30

    def test_empty_history(self) -> None:
        assert compute_delta7d_from_history([], _NOW) == 0

    def test_entry_without_created_at_skipped(self) -> None:
        entries = [{"delta": 30}]
        assert compute_delta7d_from_history(entries, _NOW) == 0

    def test_entry_at_exact_cutoff_included(self) -> None:
        cutoff = _NOW - timedelta(days=7)
        entries = [{"delta": 25, "createdAt": cutoff}]
        assert compute_delta7d_from_history(entries, _NOW) == 25

    def test_entry_just_before_cutoff_excluded(self) -> None:
        just_before = _NOW - timedelta(days=7, seconds=1)
        entries = [{"delta": 25, "createdAt": just_before}]
        assert compute_delta7d_from_history(entries, _NOW) == 0
