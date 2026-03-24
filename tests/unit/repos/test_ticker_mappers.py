from datetime import datetime, timezone

import pytest

from app.models.enums import SportEnum, TierEnum, TickerEventTypeEnum
from app.models.ticker import TickerEvent
from app.repos.mappers import to_ticker_event


class TestToTickerEvent:
    def test_upset_doc(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        expires = datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc)
        doc = {
            "type": "upset",
            "sport": "tennis",
            "region": "athens",
            "winnerUid": "user_789",
            "winnerName": "Dana",
            "loserTier": "advanced",
            "delta": 200,
            "createdAt": now,
            "expiresAt": expires,
        }

        event = to_ticker_event(doc, event_id="evt_1")

        assert isinstance(event, TickerEvent)
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

    def test_personal_best_doc(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        doc = {
            "type": "personal_best",
            "sport": "padel",
            "region": "thessaloniki",
            "userUid": "user_1",
            "userName": "Alex T.",
            "newPts": 3650,
            "previousBest": 3500,
            "createdAt": now,
            "expiresAt": now,
        }

        event = to_ticker_event(doc)

        assert event.type == TickerEventTypeEnum.PERSONAL_BEST
        assert event.user_uid == "user_1"
        assert event.user_name == "Alex T."
        assert event.new_pts == 3650
        assert event.previous_best == 3500

    def test_win_streak_doc(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        doc = {
            "type": "win_streak",
            "sport": "tennis",
            "region": "athens",
            "userUid": "user_2",
            "userName": "Eve K.",
            "streak": 5,
            "createdAt": now,
            "expiresAt": now,
        }

        event = to_ticker_event(doc)

        assert event.type == TickerEventTypeEnum.WIN_STREAK
        assert event.user_uid == "user_2"
        assert event.streak == 5

    def test_tier_crossed_doc(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        doc = {
            "type": "tier_crossed",
            "sport": "pickleball",
            "region": "athens",
            "userUid": "user_3",
            "userName": "Nick L.",
            "tierBefore": "intermediate",
            "tierAfter": "advanced",
            "direction": "up",
            "createdAt": now,
            "expiresAt": now,
        }

        event = to_ticker_event(doc)

        assert event.type == TickerEventTypeEnum.TIER_CROSSED
        assert event.tier_before == TierEnum.INTERMEDIATE
        assert event.tier_after == TierEnum.ADVANCED
        assert event.direction == "up"

    def test_minimal_doc(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        doc = {
            "type": "upset",
            "sport": "padel",
            "region": "thessaloniki",
            "createdAt": now,
            "expiresAt": now,
        }

        event = to_ticker_event(doc)

        assert event.event_id == ""
        assert event.type == TickerEventTypeEnum.UPSET
        assert event.sport == SportEnum.PADEL
        assert event.winner_uid is None
        assert event.winner_name is None
        assert event.loser_tier is None
        assert event.delta == 0

    def test_event_id_from_doc_id_field(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        doc = {
            "id": "auto_generated_id",
            "type": "personal_best",
            "sport": "pickleball",
            "region": "athens",
            "userUid": "user_2",
            "userName": "Eve K.",
            "newPts": 2800,
            "previousBest": 2700,
            "createdAt": now,
            "expiresAt": now,
        }

        event = to_ticker_event(doc)

        assert event.event_id == "auto_generated_id"

    def test_missing_required_field_raises(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        doc = {
            "sport": "tennis",
            "region": "athens",
            "createdAt": now,
            "expiresAt": now,
        }

        with pytest.raises(ValueError, match="Missing required field: type"):
            to_ticker_event(doc)
