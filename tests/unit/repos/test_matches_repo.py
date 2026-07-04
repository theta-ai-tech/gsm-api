from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.repos.matches_repo import MatchesRepo


@pytest.fixture
def mock_firestore_client():
    return Mock()


@pytest.fixture
def matches_repo(mock_firestore_client):
    return MatchesRepo(mock_firestore_client)


def _mock_match_doc(match_id: str = "match_1"):
    doc = Mock()
    doc.id = match_id
    doc.to_dict.return_value = {
        "sport": "padel",
        "status": "scheduled",
        "matchType": "singles",
        "scheduledAt": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "leagueId": "league_1",
        "divisionId": "div-1",
        "participantUids": ["user_a", "user_b"],
    }
    return doc


class TestMatchesRepoDivisionQueries:
    def _query(self, docs):
        query = Mock()
        query.where.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.start_after.return_value = query
        query.stream.return_value = docs
        return query

    def test_list_upcoming_for_division_filters_by_league_division_and_status(
        self, matches_repo, mock_firestore_client
    ):
        query = self._query([_mock_match_doc()])
        mock_firestore_client.collection.return_value = query

        results = matches_repo.list_upcoming_for_division("league_1", "div-1", limit=6)

        assert [match.match_id for match in results] == ["match_1"]
        assert query.where.call_args_list[0].args == ("leagueId", "==", "league_1")
        assert query.where.call_args_list[1].args == ("divisionId", "==", "div-1")
        assert query.where.call_args_list[2].args == ("status", "==", "scheduled")
        query.order_by.assert_any_call("scheduledAt")
        query.limit.assert_called_once_with(6)

    def test_list_completed_for_division_filters_by_league_division_and_status(
        self, matches_repo, mock_firestore_client
    ):
        doc = _mock_match_doc()
        doc.to_dict.return_value["status"] = "completed"
        doc.to_dict.return_value["finishedAt"] = datetime(
            2026, 8, 2, tzinfo=timezone.utc
        )
        query = self._query([doc])
        mock_firestore_client.collection.return_value = query

        results = matches_repo.list_completed_for_division("league_1", "div-1", limit=6)

        assert [match.match_id for match in results] == ["match_1"]
        assert query.where.call_args_list[0].args == ("leagueId", "==", "league_1")
        assert query.where.call_args_list[1].args == ("divisionId", "==", "div-1")
        assert query.where.call_args_list[2].args == ("status", "==", "completed")
        query.order_by.assert_any_call("finishedAt", direction="DESCENDING")
        query.limit.assert_called_once_with(6)
