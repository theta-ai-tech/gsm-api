from datetime import datetime, timezone

import pytest

from app.models.enums import SportEnum, TierEnum, TickerEventTypeEnum
from app.models.ticker import TickerEvent
from app.repos.mappers import to_ticker_event


class TestToTickerEvent:
    def test_complete_doc(self):
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

    def test_minimal_doc(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        doc = {
            "type": "milestone",
            "sport": "padel",
            "region": "thessaloniki",
            "winnerUid": "user_1",
            "createdAt": now,
            "expiresAt": now,
        }

        event = to_ticker_event(doc)

        assert event.event_id == ""
        assert event.type == TickerEventTypeEnum.MILESTONE
        assert event.sport == SportEnum.PADEL
        assert event.winner_name == ""
        assert event.loser_tier is None
        assert event.delta == 0

    def test_event_id_from_doc_id_field(self):
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        doc = {
            "id": "auto_generated_id",
            "type": "rising_star",
            "sport": "pickleball",
            "region": "athens",
            "winnerUid": "user_2",
            "winnerName": "Eve",
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
            "winnerUid": "user_1",
            "createdAt": now,
            "expiresAt": now,
        }

        with pytest.raises(ValueError, match="Missing required field: type"):
            to_ticker_event(doc)
