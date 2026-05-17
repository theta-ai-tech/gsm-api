from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.models.enums import LeagueStatusEnum, SportEnum
from app.repos.leagues_repo import LeaguesRepo


@pytest.fixture
def mock_firestore_client():
    return Mock()


@pytest.fixture
def leagues_repo(mock_firestore_client):
    return LeaguesRepo(mock_firestore_client)


@pytest.fixture
def sample_league_doc():
    return {
        "name": "Local Padel 2025",
        "sport": "padel",
        "status": "active",
        "ownerUid": "user_ignatios",
        "region": "athens",
        "maxPlayers": 12,
        "currentPlayers": 3,
        "startDate": datetime(2025, 9, 1, tzinfo=timezone.utc),
        "endDate": datetime(2025, 11, 30, tzinfo=timezone.utc),
        "tier": "intermediate",
        "season": "Autumn 2025",
        "meta": {},
    }


class TestLeaguesRepoListByFilter:
    def _make_mock_query(self, docs):
        mock_query = Mock()
        mock_query.where.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.start_after.return_value = mock_query
        mock_query.stream.return_value = docs
        return mock_query

    def test_list_by_filter_no_filters(
        self, leagues_repo, mock_firestore_client, sample_league_doc
    ):
        mock_doc = Mock()
        mock_doc.id = "padel-local-2025"
        mock_doc.to_dict.return_value = sample_league_doc
        mock_query = self._make_mock_query([mock_doc])
        mock_firestore_client.collection.return_value = mock_query

        results = leagues_repo.list_by_filter()

        assert len(results) == 1
        assert results[0].league_id == "padel-local-2025"
        assert results[0].sport == SportEnum.PADEL
        mock_query.where.assert_not_called()

    def test_list_by_filter_by_region(
        self, leagues_repo, mock_firestore_client, sample_league_doc
    ):
        mock_doc = Mock()
        mock_doc.id = "padel-local-2025"
        mock_doc.to_dict.return_value = sample_league_doc
        mock_query = self._make_mock_query([mock_doc])
        mock_firestore_client.collection.return_value = mock_query

        results = leagues_repo.list_by_filter(region="athens")

        assert len(results) == 1
        mock_query.where.assert_called_once_with("region", "==", "athens")

    def test_list_by_filter_all_three_filters(
        self, leagues_repo, mock_firestore_client, sample_league_doc
    ):
        mock_doc = Mock()
        mock_doc.id = "padel-local-2025"
        mock_doc.to_dict.return_value = sample_league_doc
        mock_query = self._make_mock_query([mock_doc])
        mock_firestore_client.collection.return_value = mock_query

        results = leagues_repo.list_by_filter(
            region="athens", sport=SportEnum.PADEL, status=LeagueStatusEnum.ACTIVE
        )

        assert len(results) == 1
        assert mock_query.where.call_count == 3

    def test_list_by_filter_with_cursor(
        self, leagues_repo, mock_firestore_client, sample_league_doc
    ):
        mock_doc = Mock()
        mock_doc.id = "padel-local-2025"
        mock_doc.to_dict.return_value = sample_league_doc
        mock_query = self._make_mock_query([mock_doc])
        mock_firestore_client.collection.return_value = mock_query

        cursor = {
            "startDate": datetime(2025, 9, 1, tzinfo=timezone.utc),
            "leagueId": "some-previous-league",
        }
        results = leagues_repo.list_by_filter(cursor=cursor)

        assert len(results) == 1
        mock_query.start_after.assert_called_once()

    def test_list_by_filter_empty_result(self, leagues_repo, mock_firestore_client):
        mock_query = self._make_mock_query([])
        mock_firestore_client.collection.return_value = mock_query

        results = leagues_repo.list_by_filter(region="nowhere")

        assert results == []


class TestLeaguesRepoGetMemberCount:
    def test_get_member_count_from_field(self, leagues_repo, mock_firestore_client):
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.id = "padel-local-2025"
        mock_doc.to_dict.return_value = {
            "sport": "padel",
            "status": "active",
            "currentPlayers": 7,
        }
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        count = leagues_repo.get_member_count("padel-local-2025")

        assert count == 7

    def test_get_member_count_zero_is_valid(self, leagues_repo, mock_firestore_client):
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.id = "padel-local-2025"
        mock_doc.to_dict.return_value = {
            "sport": "padel",
            "status": "active",
            "currentPlayers": 0,
        }
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        count = leagues_repo.get_member_count("padel-local-2025")

        assert count == 0

    def test_get_member_count_fallback_to_subcollection(
        self, leagues_repo, mock_firestore_client
    ):
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.id = "padel-local-2025"
        mock_doc.to_dict.return_value = {"sport": "padel", "status": "active"}

        mock_member1 = Mock()
        mock_member2 = Mock()

        mock_league_ref = Mock()
        mock_league_ref.get.return_value = mock_doc
        mock_league_ref.collection.return_value.stream.return_value = [
            mock_member1,
            mock_member2,
        ]

        mock_firestore_client.collection.return_value.document.return_value = (
            mock_league_ref
        )

        count = leagues_repo.get_member_count("padel-local-2025")

        assert count == 2

    def test_get_member_count_doc_not_found(self, leagues_repo, mock_firestore_client):
        mock_doc = Mock()
        mock_doc.exists = False
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        count = leagues_repo.get_member_count("nonexistent")

        assert count == 0


class TestLeaguesRepoIncrementMemberCount:
    def test_increment_member_count_default(self, leagues_repo, mock_firestore_client):
        mock_doc_ref = Mock()
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        leagues_repo.increment_member_count("padel-local-2025")

        mock_doc_ref.update.assert_called_once()
        call_args = mock_doc_ref.update.call_args[0][0]
        assert "currentPlayers" in call_args

    def test_increment_member_count_custom_delta(
        self, leagues_repo, mock_firestore_client
    ):
        mock_doc_ref = Mock()
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        leagues_repo.increment_member_count("padel-local-2025", delta=3)

        mock_doc_ref.update.assert_called_once()

    def test_decrement_member_count(self, leagues_repo, mock_firestore_client):
        mock_doc_ref = Mock()
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        leagues_repo.increment_member_count("padel-local-2025", delta=-1)

        mock_doc_ref.update.assert_called_once()
        call_args = mock_doc_ref.update.call_args[0][0]
        assert "currentPlayers" in call_args
