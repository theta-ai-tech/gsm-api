from datetime import datetime, timezone

from app.models.enums import SportEnum, TierEnum
from app.models.leaderboard import LeaderboardSnapshot
from app.repos.mappers import to_leaderboard_snapshot


class TestToLeaderboardSnapshot:
    def test_complete_doc(self):
        now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        doc = {
            "region": "athens",
            "sport": "tennis",
            "entries": [
                {
                    "uid": "user_123",
                    "name": "Alex",
                    "pts": 3450,
                    "tier": "advanced",
                    "rank": 1,
                    "delta7d": 250,
                },
                {
                    "uid": "user_456",
                    "name": "Sam",
                    "pts": 3200,
                    "tier": "advanced",
                    "rank": 2,
                    "delta7d": -50,
                },
            ],
            "risingStars": [
                {
                    "uid": "user_789",
                    "name": "Dana",
                    "pts": 2100,
                    "delta7d": 400,
                    "rank": 15,
                },
            ],
            "lastUpdated": now,
        }

        snap = to_leaderboard_snapshot(doc)

        assert isinstance(snap, LeaderboardSnapshot)
        assert snap.region == "athens"
        assert snap.sport == SportEnum.TENNIS
        assert len(snap.entries) == 2
        assert snap.entries[0].uid == "user_123"
        assert snap.entries[0].pts == 3450
        assert snap.entries[0].tier == TierEnum.ADVANCED
        assert snap.entries[0].rank == 1
        assert snap.entries[0].delta7d == 250
        assert snap.entries[1].uid == "user_456"
        assert snap.entries[1].delta7d == -50
        assert len(snap.rising_stars) == 1
        assert snap.rising_stars[0].uid == "user_789"
        assert snap.rising_stars[0].delta7d == 400
        assert snap.rising_stars[0].rank == 15
        assert snap.last_updated == now

    def test_empty_doc(self):
        doc = {"region": "thessaloniki", "sport": "padel"}
        snap = to_leaderboard_snapshot(doc)
        assert snap.region == "thessaloniki"
        assert snap.sport == SportEnum.PADEL
        assert snap.entries == []
        assert snap.rising_stars == []
        assert snap.last_updated is None

    def test_missing_optional_fields_in_entry(self):
        doc = {
            "region": "athens",
            "sport": "tennis",
            "entries": [
                {"uid": "user_1", "name": "Bob", "pts": 1000, "rank": 5},
            ],
            "risingStars": [],
        }
        snap = to_leaderboard_snapshot(doc)
        assert len(snap.entries) == 1
        assert snap.entries[0].tier is None
        assert snap.entries[0].delta7d == 0

    def test_null_entries_and_rising_stars(self):
        doc = {
            "region": "athens",
            "sport": "tennis",
            "entries": None,
            "risingStars": None,
        }
        snap = to_leaderboard_snapshot(doc)
        assert snap.entries == []
        assert snap.rising_stars == []
