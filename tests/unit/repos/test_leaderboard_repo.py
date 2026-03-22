from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.models.leaderboard import LeaderboardSnapshot
from app.repos.leaderboard_repo import LeaderboardRepo

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]


def _make_repo() -> tuple[LeaderboardRepo, MagicMock]:
    mock_client = MagicMock(spec=firestore.Client)
    return LeaderboardRepo(mock_client), mock_client


class TestGetSnapshot:
    def test_returns_none_when_doc_missing(self):
        repo, client = _make_repo()
        mock_snap = MagicMock()
        mock_snap.exists = False
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_snapshot("athens", "tennis")

        assert result is None
        client.collection.assert_called_once_with("leaderboards")
        client.collection.return_value.document.assert_called_once_with("athens_tennis")

    def test_returns_snapshot_with_data(self):
        repo, client = _make_repo()
        now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {
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
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_snapshot("athens", "tennis")

        assert result is not None
        assert isinstance(result, LeaderboardSnapshot)
        assert result.region == "athens"
        assert result.sport == "tennis"
        assert len(result.entries) == 1
        assert result.entries[0].uid == "user_123"
        assert result.entries[0].pts == 3450
        assert len(result.rising_stars) == 1
        assert result.rising_stars[0].uid == "user_789"
        assert result.last_updated == now

    def test_returns_empty_snapshot(self):
        repo, client = _make_repo()
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {
            "region": "athens",
            "sport": "padel",
        }
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_snapshot("athens", "padel")

        assert result is not None
        assert result.entries == []
        assert result.rising_stars == []


class TestListByRegion:
    def test_returns_snapshots_for_region(self):
        repo, client = _make_repo()
        mock_doc1 = MagicMock()
        mock_doc1.to_dict.return_value = {
            "region": "athens",
            "sport": "tennis",
            "entries": [],
            "risingStars": [],
        }
        mock_doc2 = MagicMock()
        mock_doc2.to_dict.return_value = {
            "region": "athens",
            "sport": "padel",
            "entries": [],
            "risingStars": [],
        }
        query_mock = MagicMock()
        query_mock.stream.return_value = [mock_doc1, mock_doc2]
        client.collection.return_value.where.return_value = query_mock

        results = repo.list_by_region("athens")

        assert len(results) == 2
        assert results[0].sport == "tennis"
        assert results[1].sport == "padel"
        client.collection.assert_called_once_with("leaderboards")
        client.collection.return_value.where.assert_called_once_with(
            "region", "==", "athens"
        )

    def test_returns_empty_list_when_no_docs(self):
        repo, client = _make_repo()
        query_mock = MagicMock()
        query_mock.stream.return_value = []
        client.collection.return_value.where.return_value = query_mock

        results = repo.list_by_region("unknown_region")

        assert results == []


class TestListBySport:
    def test_returns_snapshots_for_sport(self):
        repo, client = _make_repo()
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = {
            "region": "athens",
            "sport": "tennis",
            "entries": [],
            "risingStars": [],
        }
        query_mock = MagicMock()
        query_mock.stream.return_value = [mock_doc]
        client.collection.return_value.where.return_value = query_mock

        results = repo.list_by_sport("tennis")

        assert len(results) == 1
        assert results[0].region == "athens"
        client.collection.return_value.where.assert_called_once_with(
            "sport", "==", "tennis"
        )
