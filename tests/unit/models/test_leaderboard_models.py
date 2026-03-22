from datetime import datetime, timezone

from app.models.enums import SportEnum, TierEnum
from app.models.leaderboard import (
    LeaderboardEntry,
    LeaderboardSnapshot,
    RisingStarEntry,
)


class TestLeaderboardEntry:
    def test_full_entry(self):
        entry = LeaderboardEntry(
            uid="user_123", name="Alex", pts=3450, tier="advanced", rank=1, delta7d=250
        )
        assert entry.uid == "user_123"
        assert entry.name == "Alex"
        assert entry.pts == 3450
        assert entry.tier == TierEnum.ADVANCED
        assert entry.rank == 1
        assert entry.delta7d == 250

    def test_defaults(self):
        entry = LeaderboardEntry(uid="user_1", name="Bob", pts=1000, rank=5)
        assert entry.tier is None
        assert entry.delta7d == 0


class TestRisingStarEntry:
    def test_full_entry(self):
        star = RisingStarEntry(
            uid="user_789", name="Dana", pts=2100, delta7d=400, rank=15
        )
        assert star.uid == "user_789"
        assert star.name == "Dana"
        assert star.pts == 2100
        assert star.delta7d == 400
        assert star.rank == 15

    def test_defaults(self):
        star = RisingStarEntry(uid="user_1", name="Eve", pts=1500, rank=10)
        assert star.delta7d == 0


class TestLeaderboardSnapshot:
    def test_minimal(self):
        snap = LeaderboardSnapshot(region="athens", sport=SportEnum.TENNIS)
        assert snap.region == "athens"
        assert snap.sport == SportEnum.TENNIS
        assert snap.entries == []
        assert snap.rising_stars == []
        assert snap.last_updated is None

    def test_with_entries_and_rising_stars(self):
        now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        entry = LeaderboardEntry(
            uid="user_123", name="Alex", pts=3450, tier="advanced", rank=1, delta7d=250
        )
        star = RisingStarEntry(
            uid="user_789", name="Dana", pts=2100, delta7d=400, rank=15
        )
        snap = LeaderboardSnapshot(
            region="athens",
            sport=SportEnum.TENNIS,
            entries=[entry],
            rising_stars=[star],
            last_updated=now,
        )
        assert len(snap.entries) == 1
        assert snap.entries[0].uid == "user_123"
        assert len(snap.rising_stars) == 1
        assert snap.rising_stars[0].uid == "user_789"
        assert snap.last_updated == now
