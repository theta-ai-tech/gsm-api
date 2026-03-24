from datetime import datetime, timezone
from unittest.mock import MagicMock

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.enums import SportEnum, TierEnum, TickerEventTypeEnum
from app.models.ticker import TickerEvent
from app.repos.ticker_repo import TickerRepo


def _make_repo() -> tuple[TickerRepo, MagicMock]:
    mock_client = MagicMock(spec=firestore.Client)
    return TickerRepo(mock_client), mock_client


def _sample_upset() -> TickerEvent:
    return TickerEvent(
        event_id="",
        type=TickerEventTypeEnum.UPSET,
        sport=SportEnum.TENNIS,
        region="athens",
        winner_uid="user_789",
        winner_name="Dana",
        loser_tier=TierEnum.ADVANCED,
        delta=200,
        created_at=datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc),
    )


class TestAdd:
    def test_adds_upset_event_and_returns_id(self):
        repo, client = _make_repo()
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "auto_id_123"
        client.collection.return_value.add.return_value = (None, mock_doc_ref)

        event = _sample_upset()
        result = repo.add(event)

        assert result == "auto_id_123"
        client.collection.assert_called_once_with("ticker")
        call_args = client.collection.return_value.add.call_args
        doc_data = call_args[0][0]
        assert doc_data["type"] == "upset"
        assert doc_data["sport"] == "tennis"
        assert doc_data["region"] == "athens"
        assert doc_data["winnerUid"] == "user_789"
        assert doc_data["winnerName"] == "Dana"
        assert doc_data["loserTier"] == "advanced"
        assert doc_data["delta"] == 200

    def test_adds_personal_best_event(self):
        repo, client = _make_repo()
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "auto_id_pb"
        client.collection.return_value.add.return_value = (None, mock_doc_ref)

        event = TickerEvent(
            type=TickerEventTypeEnum.PERSONAL_BEST,
            sport=SportEnum.PADEL,
            region="thessaloniki",
            user_uid="user_1",
            user_name="Alex T.",
            new_pts=3650,
            previous_best=3500,
            created_at=datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc),
        )
        result = repo.add(event)

        assert result == "auto_id_pb"
        call_args = client.collection.return_value.add.call_args
        doc_data = call_args[0][0]
        assert doc_data["type"] == "personal_best"
        assert doc_data["userUid"] == "user_1"
        assert doc_data["userName"] == "Alex T."
        assert doc_data["newPts"] == 3650
        assert doc_data["previousBest"] == 3500
        assert "winnerUid" not in doc_data
        assert "loserTier" not in doc_data

    def test_adds_win_streak_event(self):
        repo, client = _make_repo()
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "auto_id_ws"
        client.collection.return_value.add.return_value = (None, mock_doc_ref)

        event = TickerEvent(
            type=TickerEventTypeEnum.WIN_STREAK,
            sport=SportEnum.TENNIS,
            region="athens",
            user_uid="user_2",
            user_name="Eve K.",
            streak=10,
            created_at=datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc),
        )
        result = repo.add(event)

        assert result == "auto_id_ws"
        call_args = client.collection.return_value.add.call_args
        doc_data = call_args[0][0]
        assert doc_data["type"] == "win_streak"
        assert doc_data["userUid"] == "user_2"
        assert doc_data["streak"] == 10

    def test_adds_tier_crossed_event(self):
        repo, client = _make_repo()
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "auto_id_tc"
        client.collection.return_value.add.return_value = (None, mock_doc_ref)

        event = TickerEvent(
            type=TickerEventTypeEnum.TIER_CROSSED,
            sport=SportEnum.PICKLEBALL,
            region="athens",
            user_uid="user_3",
            user_name="Nick L.",
            tier_before=TierEnum.INTERMEDIATE,
            tier_after=TierEnum.ADVANCED,
            direction="up",
            created_at=datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc),
        )
        result = repo.add(event)

        assert result == "auto_id_tc"
        call_args = client.collection.return_value.add.call_args
        doc_data = call_args[0][0]
        assert doc_data["type"] == "tier_crossed"
        assert doc_data["tierBefore"] == "intermediate"
        assert doc_data["tierAfter"] == "advanced"
        assert doc_data["direction"] == "up"

    def test_omits_none_optional_fields(self):
        repo, client = _make_repo()
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "auto_id_minimal"
        client.collection.return_value.add.return_value = (None, mock_doc_ref)

        event = TickerEvent(
            type=TickerEventTypeEnum.UPSET,
            sport=SportEnum.PADEL,
            region="thessaloniki",
            created_at=datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc),
        )
        repo.add(event)

        call_args = client.collection.return_value.add.call_args
        doc_data = call_args[0][0]
        assert "winnerUid" not in doc_data
        assert "loserTier" not in doc_data
        assert "delta" not in doc_data
        assert "userUid" not in doc_data
        assert "streak" not in doc_data
        assert "tierBefore" not in doc_data


class TestListByRegionSport:
    def test_returns_events(self):
        repo, client = _make_repo()
        now = datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc)
        expires = datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc)

        mock_doc = MagicMock()
        mock_doc.id = "evt_1"
        mock_doc.to_dict.return_value = {
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

        query_mock = MagicMock()
        query_mock.stream.return_value = [mock_doc]
        (
            client.collection.return_value.where.return_value.where.return_value.order_by.return_value.limit.return_value
        ) = query_mock

        results = repo.list_by_region_sport("athens", "tennis")

        assert len(results) == 1
        assert results[0].event_id == "evt_1"
        assert results[0].type == TickerEventTypeEnum.UPSET
        assert results[0].sport == SportEnum.TENNIS
        client.collection.assert_called_once_with("ticker")

    def test_returns_empty_list_when_no_docs(self):
        repo, client = _make_repo()

        query_mock = MagicMock()
        query_mock.stream.return_value = []
        (
            client.collection.return_value.where.return_value.where.return_value.order_by.return_value.limit.return_value
        ) = query_mock

        results = repo.list_by_region_sport("unknown", "tennis")

        assert results == []

    def test_respects_limit_parameter(self):
        repo, client = _make_repo()

        query_mock = MagicMock()
        query_mock.stream.return_value = []
        limit_mock = MagicMock(return_value=query_mock)
        (
            client.collection.return_value.where.return_value.where.return_value.order_by.return_value
        ).limit = limit_mock

        repo.list_by_region_sport("athens", "tennis", limit=5)

        limit_mock.assert_called_once_with(5)
