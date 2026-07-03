from unittest.mock import Mock

import pytest

from app.models import Division, RatingRange
from app.models.enums import LeagueStatusEnum
from app.repos.divisions_repo import DivisionsRepo


@pytest.fixture
def mock_firestore_client():
    return Mock()


@pytest.fixture
def divisions_repo(mock_firestore_client):
    return DivisionsRepo(mock_firestore_client)


def _division_doc(
    name: str = "Division 1",
    ordinal: int = 1,
    min_pts: int = 1000,
    max_pts: int = 1400,
    current_players: int = 6,
):
    return {
        "name": name,
        "ordinal": ordinal,
        "ratingRange": {"min": min_pts, "max": max_pts},
        "currentPlayers": current_players,
        "status": "active",
    }


class TestDivisionsRepo:
    def test_get_by_id_returns_none_for_missing_doc(
        self, divisions_repo, mock_firestore_client
    ):
        mock_doc = Mock()
        mock_doc.exists = False
        (
            mock_firestore_client.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
        ) = mock_doc

        result = divisions_repo.get_by_id("league_1", "missing")

        assert result is None

    def test_get_by_id_maps_existing_division(
        self, divisions_repo, mock_firestore_client
    ):
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.id = "div-1"
        mock_doc.to_dict.return_value = _division_doc()
        (
            mock_firestore_client.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
        ) = mock_doc

        result = divisions_repo.get_by_id("league_1", "div-1")

        assert result is not None
        assert result.division_id == "div-1"
        assert result.ordinal == 1

    def test_list_for_league_orders_by_ordinal(
        self, divisions_repo, mock_firestore_client
    ):
        mock_doc = Mock()
        mock_doc.id = "div-1"
        mock_doc.to_dict.return_value = _division_doc()

        mock_query = Mock()
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.stream.return_value = [mock_doc]
        (
            mock_firestore_client.collection.return_value.document.return_value.collection.return_value
        ) = mock_query

        result = divisions_repo.list_for_league("league_1")

        assert [division.division_id for division in result] == ["div-1"]
        mock_query.order_by.assert_called_once_with("ordinal")

    def test_create_division_writes_firestore_shape(
        self, divisions_repo, mock_firestore_client
    ):
        mock_doc_ref = Mock()
        (
            mock_firestore_client.collection.return_value.document.return_value.collection.return_value.document.return_value
        ) = mock_doc_ref
        division = Division(
            division_id="div-1",
            name="Division 1",
            ordinal=1,
            rating_range=RatingRange(min=1000, max=1400),
            current_players=6,
            status=LeagueStatusEnum.ACTIVE,
        )

        divisions_repo.create_division("league_1", division)

        mock_doc_ref.set.assert_called_once_with(
            {
                "name": "Division 1",
                "ordinal": 1,
                "ratingRange": {"min": 1000, "max": 1400},
                "currentPlayers": 6,
                "status": "active",
            }
        )

    def test_set_division_current_players_updates_only_count(
        self, divisions_repo, mock_firestore_client
    ):
        mock_doc_ref = Mock()
        (
            mock_firestore_client.collection.return_value.document.return_value.collection.return_value.document.return_value
        ) = mock_doc_ref

        divisions_repo.set_division_current_players("league_1", "div-1", 5)

        mock_doc_ref.update.assert_called_once_with({"currentPlayers": 5})
