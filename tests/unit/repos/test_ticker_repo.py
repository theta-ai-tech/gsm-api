from datetime import datetime, timezone
from unittest.mock import MagicMock

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.enums import SportEnum, TickerEventTypeEnum
from app.models.ticker import TickerEvent
from app.repos.ticker_repo import TickerRepo


def _make_repo() -> tuple[TickerRepo, MagicMock]:
    mock_client = MagicMock(spec=firestore.Client)
    return TickerRepo(mock_client), mock_client


def _sample_event() -> TickerEvent:
    return TickerEvent(
        event_id="",
        type=TickerEventTypeEnum.UPSET,
        sport=SportEnum.TENNIS,
        region="athens",
        winner_uid="user_789",
        winner_name="Dana",
        loser_tier="advanced",
        delta=200,
        created_at=datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc),
    )


class TestAdd:
    def test_adds_event_and_returns_id(self):
        repo, client = _make_repo()
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "auto_id_123"
        client.collection.return_value.add.return_value = (None, mock_doc_ref)

        event = _sample_event()
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

    def test_adds_event_without_loser_tier(self):
        repo, client = _make_repo()
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "auto_id_456"
        client.collection.return_value.add.return_value = (None, mock_doc_ref)

        event = TickerEvent(
            type=TickerEventTypeEnum.MILESTONE,
            sport=SportEnum.PADEL,
            region="thessaloniki",
            winner_uid="user_1",
            winner_name="Alex",
            created_at=datetime(2026, 3, 1, 14, 30, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 3, 2, 14, 30, 0, tzinfo=timezone.utc),
        )
        result = repo.add(event)

        assert result == "auto_id_456"
        call_args = client.collection.return_value.add.call_args
        doc_data = call_args[0][0]
        assert doc_data["loserTier"] is None
        assert doc_data["delta"] == 0


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
