"""Unit tests for the D7 leaderboard computation (pure functions)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from functions.scheduled.leaderboard_computation import (
    build_area_to_region,
    build_leaderboard_entries,
    build_rising_stars,
    build_uid_to_rank,
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

    def test_tombstoned_user_excluded(self) -> None:
        # ACCT-1: anonymized (deleted) users must drop out of leaderboards.
        area_to_region = {101: "athens"}
        deleted = _make_user("u1", "Deleted Player", 101, {"tennis": 800})
        deleted["isDeleted"] = True
        active = _make_user("u2", "Alice", 101, {"tennis": 600})
        buckets = extract_users_by_region_sport([deleted, active], area_to_region)
        bucket = buckets[("athens", "tennis")]
        assert len(bucket) == 1
        assert bucket[0]["uid"] == "u2"


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
# build_uid_to_rank
# ---------------------------------------------------------------------------


class TestBuildUidToRank:
    def test_ranks_by_pts_desc(self) -> None:
        users = [
            _make_user("u1", "Alice", 101, {"tennis": 500}),
            _make_user("u2", "Bob", 101, {"tennis": 800}),
            _make_user("u3", "Carol", 101, {"tennis": 600}),
        ]
        result = build_uid_to_rank(users, "tennis")
        assert result == {"u2": 1, "u3": 2, "u1": 3}

    def test_empty_users(self) -> None:
        assert build_uid_to_rank([], "tennis") == {}

    def test_skips_users_without_pts(self) -> None:
        users = [
            _make_user("u1", "Alice", 101, {"tennis": 500}),
            {"uid": "u2", "name": "Bob", "rankings": {"tennis": {"sport": "tennis"}}},
        ]
        result = build_uid_to_rank(users, "tennis")
        assert result == {"u1": 1}


# ---------------------------------------------------------------------------
# build_rising_stars
# ---------------------------------------------------------------------------


class TestBuildRisingStars:
    def test_sorts_by_delta7d_desc_with_overall_rank(self) -> None:
        users = [
            _make_user("u1", "Alice", 101, {"tennis": 500}),
            _make_user("u2", "Bob", 101, {"tennis": 800}),
            _make_user("u3", "Carol", 101, {"tennis": 600}),
        ]
        delta7d_map = {"u1": 50, "u2": 30, "u3": 80}
        uid_to_rank = build_uid_to_rank(users, "tennis")
        stars = build_rising_stars(users, "tennis", delta7d_map, uid_to_rank)
        # Sorted by delta7d DESC: u3(80) > u1(50) > u2(30)
        assert stars[0]["uid"] == "u3"
        assert stars[0]["delta7d"] == 80
        # u3 has 600 pts -> overall rank 2 (u2=800 is rank 1)
        assert stars[0]["rank"] == 2
        assert stars[1]["uid"] == "u1"
        # u1 has 500 pts -> overall rank 3
        assert stars[1]["rank"] == 3
        assert stars[2]["uid"] == "u2"
        # u2 has 800 pts -> overall rank 1
        assert stars[2]["rank"] == 1

    def test_excludes_zero_or_negative_delta(self) -> None:
        users = [
            _make_user("u1", "Alice", 101, {"tennis": 500}),
            _make_user("u2", "Bob", 101, {"tennis": 800}),
        ]
        delta7d_map = {"u1": 0, "u2": -10}
        uid_to_rank = build_uid_to_rank(users, "tennis")
        stars = build_rising_stars(users, "tennis", delta7d_map, uid_to_rank)
        assert stars == []

    def test_respects_top_n(self) -> None:
        users = [
            _make_user(f"u{i}", f"User{i}", 101, {"tennis": i * 100}) for i in range(10)
        ]
        delta7d_map = {f"u{i}": (i + 1) * 10 for i in range(10)}
        uid_to_rank = build_uid_to_rank(users, "tennis")
        stars = build_rising_stars(users, "tennis", delta7d_map, uid_to_rank, top_n=5)
        assert len(stars) == 5
        assert stars[0]["delta7d"] == 100

    def test_empty_users(self) -> None:
        stars = build_rising_stars([], "tennis", {}, {})
        assert stars == []

    def test_includes_pts(self) -> None:
        users = [_make_user("u1", "Alice", 101, {"tennis": 750})]
        delta7d_map = {"u1": 25}
        uid_to_rank = build_uid_to_rank(users, "tennis")
        stars = build_rising_stars(users, "tennis", delta7d_map, uid_to_rank)
        assert stars[0]["pts"] == 750

    def test_rank_reflects_overall_position_not_rising_stars_position(self) -> None:
        """Verify that rank is the overall leaderboard position, not 1..N within stars."""
        users = [
            _make_user(f"u{i}", f"User{i}", 101, {"tennis": (20 - i) * 100})
            for i in range(20)
        ]
        # Only u15 and u18 have positive deltas — they're low in pts
        delta7d_map = {"u15": 40, "u18": 20}
        uid_to_rank = build_uid_to_rank(users, "tennis")
        stars = build_rising_stars(users, "tennis", delta7d_map, uid_to_rank)
        assert len(stars) == 2
        # u15 has pts=(20-15)*100=500, overall rank 16
        assert stars[0]["uid"] == "u15"
        assert stars[0]["rank"] == 16
        # u18 has pts=(20-18)*100=200, overall rank 19
        assert stars[1]["uid"] == "u18"
        assert stars[1]["rank"] == 19


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
