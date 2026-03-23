from datetime import datetime, timezone

from app.models.enums import SportEnum, TierEnum, TickerEventTypeEnum
from app.models.ticker import TickerEvent


class TestTickerEvent:
    def test_full_event(self):
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

    def test_defaults(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        event = TickerEvent(
            type="milestone",
            sport="padel",
            region="thessaloniki",
            winner_uid="user_1",
            winner_name="Alex",
            created_at=now,
            expires_at=now,
        )
        assert event.event_id == ""
        assert event.type == TickerEventTypeEnum.MILESTONE
        assert event.loser_tier is None
        assert event.delta == 0

    def test_rising_star_type(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        event = TickerEvent(
            type="rising_star",
            sport="pickleball",
            region="athens",
            winner_uid="user_2",
            winner_name="Eve",
            created_at=now,
            expires_at=now,
        )
        assert event.type == TickerEventTypeEnum.RISING_STAR


class TestTickerEventTypeEnum:
    def test_values(self):
        assert TickerEventTypeEnum.UPSET == "upset"
        assert TickerEventTypeEnum.MILESTONE == "milestone"
        assert TickerEventTypeEnum.RISING_STAR == "rising_star"

    def test_all_members(self):
        assert len(TickerEventTypeEnum) == 3
