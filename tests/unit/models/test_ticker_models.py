from datetime import datetime, timezone

import pytest

from app.models.enums import SportEnum, TierEnum, TickerEventTypeEnum
from app.models.ticker import TickerEvent


class TestTickerEvent:
    def test_upset_event(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        expires = datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc)
        event = TickerEvent(
            event_id="evt_1",
            type=TickerEventTypeEnum.UPSET,
            sport=SportEnum.TENNIS,
            region="athens",
            winner_uid="user_789",
            winner_name="Dana",
            loser_tier=TierEnum.ADVANCED,
            delta=200,
            created_at=now,
            expires_at=expires,
        )
        assert event.event_id == "evt_1"
        assert event.type == TickerEventTypeEnum.UPSET
        assert event.sport == SportEnum.TENNIS
        assert event.region == "athens"
        assert event.winner_uid == "user_789"
        assert event.winner_name == "Dana"
        assert event.loser_tier == TierEnum.ADVANCED
        assert event.delta == 200
        assert event.created_at == now
        assert event.expires_at == expires

    def test_personal_best_event(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        event = TickerEvent(
            type=TickerEventTypeEnum.PERSONAL_BEST,
            sport=SportEnum.PADEL,
            region="thessaloniki",
            user_uid="user_1",
            user_name="Alex T.",
            new_pts=3650,
            previous_best=3500,
            created_at=now,
            expires_at=now,
        )
        assert event.type == TickerEventTypeEnum.PERSONAL_BEST
        assert event.user_uid == "user_1"
        assert event.user_name == "Alex T."
        assert event.new_pts == 3650
        assert event.previous_best == 3500

    def test_win_streak_event(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        event = TickerEvent(
            type=TickerEventTypeEnum.WIN_STREAK,
            sport=SportEnum.TENNIS,
            region="athens",
            user_uid="user_2",
            user_name="Eve K.",
            streak=5,
            created_at=now,
            expires_at=now,
        )
        assert event.type == TickerEventTypeEnum.WIN_STREAK
        assert event.streak == 5

    def test_tier_crossed_event(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        event = TickerEvent(
            type=TickerEventTypeEnum.TIER_CROSSED,
            sport=SportEnum.PICKLEBALL,
            region="athens",
            user_uid="user_3",
            user_name="Nick L.",
            tier_before=TierEnum.INTERMEDIATE,
            tier_after=TierEnum.ADVANCED,
            direction="up",
            created_at=now,
            expires_at=now,
        )
        assert event.type == TickerEventTypeEnum.TIER_CROSSED
        assert event.tier_before == TierEnum.INTERMEDIATE
        assert event.tier_after == TierEnum.ADVANCED
        assert event.direction == "up"

    def test_defaults_on_valid_upset(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        event = TickerEvent(
            type="upset",
            sport="padel",
            region="thessaloniki",
            winner_uid="user_1",
            winner_name="Test",
            loser_tier=TierEnum.ADVANCED,
            created_at=now,
            expires_at=now,
        )
        assert event.event_id == ""
        assert event.delta == 0
        assert event.user_uid is None
        assert event.new_pts is None
        assert event.streak is None
        assert event.tier_before is None

    def test_upset_missing_required_fields_raises(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="requires fields"):
            TickerEvent(
                type="upset",
                sport="padel",
                region="thessaloniki",
                created_at=now,
                expires_at=now,
            )

    def test_personal_best_missing_required_fields_raises(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="requires fields"):
            TickerEvent(
                type="personal_best",
                sport="padel",
                region="thessaloniki",
                user_uid="user_1",
                user_name="Test",
                created_at=now,
                expires_at=now,
            )

    def test_win_streak_missing_streak_raises(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="requires fields"):
            TickerEvent(
                type="win_streak",
                sport="tennis",
                region="athens",
                user_uid="user_2",
                user_name="Eve K.",
                created_at=now,
                expires_at=now,
            )

    def test_tier_crossed_missing_direction_raises(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="requires fields"):
            TickerEvent(
                type="tier_crossed",
                sport="pickleball",
                region="athens",
                user_uid="user_3",
                user_name="Nick L.",
                tier_before=TierEnum.INTERMEDIATE,
                tier_after=TierEnum.ADVANCED,
                created_at=now,
                expires_at=now,
            )


class TestTickerEventTypeEnum:
    def test_values(self):
        assert TickerEventTypeEnum.UPSET == "upset"
        assert TickerEventTypeEnum.PERSONAL_BEST == "personal_best"
        assert TickerEventTypeEnum.WIN_STREAK == "win_streak"
        assert TickerEventTypeEnum.TIER_CROSSED == "tier_crossed"

    def test_all_members(self):
        assert len(TickerEventTypeEnum) == 4
