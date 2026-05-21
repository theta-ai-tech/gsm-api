"""Unit tests for GET /leagues."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_leagues_repo
from app.deps import get_current_user, get_role_service
from app.main import app
from app.models.enums import LeagueStatusEnum, SportEnum
from app.models.league import League
from app.security import CurrentUser

_UID = "user_test"


@pytest.fixture()
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email="test@gsm.local"
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def mock_leagues_repo():
    repo = Mock(
        spec_set=[
            "list_by_filter",
            "get_by_id",
            "list_members",
            "get_member_count",
            "increment_member_count",
        ]
    )
    repo.list_by_filter.return_value = []
    app.dependency_overrides[get_leagues_repo] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_leagues_repo, None)


@pytest.fixture()
def client(_override_auth, mock_leagues_repo):
    return TestClient(app)


def _make_league(
    league_id: str = "lg1",
    name: str = "Test League",
    sport: SportEnum = SportEnum.PADEL,
    status: LeagueStatusEnum = LeagueStatusEnum.OPEN,
    start_date: datetime | None = datetime(2026, 6, 1, tzinfo=timezone.utc),
    **kwargs,
) -> League:
    return League(
        league_id=league_id,
        name=name,
        sport=sport,
        status=status,
        owner_uid="owner1",
        start_date=start_date,
        **kwargs,
    )


class TestGetLeaguesHappyPath:
    def test_returns_200_with_leagues(
        self, client: TestClient, mock_leagues_repo: Mock
    ):
        mock_leagues_repo.list_by_filter.return_value = [
            _make_league("lg1", "League A"),
            _make_league("lg2", "League B"),
        ]
        resp = client.get("/leagues")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["leagues"]) == 2

    def test_response_shape(self, client: TestClient, mock_leagues_repo: Mock):
        mock_leagues_repo.list_by_filter.return_value = [
            _make_league(
                "lg1",
                region="athens",
                tier="intermediate",
                max_players=12,
                current_players=3,
            )
        ]
        resp = client.get("/leagues")
        assert resp.status_code == 200
        card = resp.json()["leagues"][0]
        assert set(card.keys()) == {
            "league_id",
            "name",
            "sport",
            "status",
            "region",
            "tier",
            "max_players",
            "current_players",
            "start_date",
        }
        assert card["league_id"] == "lg1"
        assert card["region"] == "athens"
        assert card["tier"] == "intermediate"
        assert card["max_players"] == 12
        assert card["current_players"] == 3

    def test_empty_result_returns_200_with_empty_list(
        self, client: TestClient, mock_leagues_repo: Mock
    ):
        mock_leagues_repo.list_by_filter.return_value = []
        resp = client.get("/leagues")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"leagues": [], "next_cursor": None}

    def test_next_cursor_is_none_when_fewer_than_limit(
        self, client: TestClient, mock_leagues_repo: Mock
    ):
        mock_leagues_repo.list_by_filter.return_value = [
            _make_league(f"lg{i}") for i in range(3)
        ]
        resp = client.get("/leagues", params={"limit": 5})
        assert resp.status_code == 200
        assert resp.json()["next_cursor"] is None


class TestGetLeaguesPagination:
    def test_next_cursor_set_when_more_results(
        self, client: TestClient, mock_leagues_repo: Mock
    ):
        # 21 results with limit=20 → has_more=True
        mock_leagues_repo.list_by_filter.return_value = [
            _make_league(f"lg{i}") for i in range(21)
        ]
        resp = client.get("/leagues", params={"limit": 20})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["leagues"]) == 20
        assert body["next_cursor"] is not None

    def test_next_cursor_is_none_when_last_item_has_no_start_date(
        self, client: TestClient, mock_leagues_repo: Mock
    ):
        # 5 items in the page, the 5th has no start_date; plus a 6th to trigger has_more
        results = [_make_league(f"lg{i}") for i in range(4)]
        results.append(_make_league("lg4_no_date", start_date=None))
        results.append(_make_league("lg5_extra"))  # over-fetch item — triggers has_more
        mock_leagues_repo.list_by_filter.return_value = results
        resp = client.get("/leagues", params={"limit": 5})
        assert resp.status_code == 200
        # page[-1] has no start_date → _encode_cursor returns None → next_cursor is None
        assert resp.json()["next_cursor"] is None

    def test_cursor_param_passed_to_repo(
        self, client: TestClient, mock_leagues_repo: Mock
    ):
        mock_leagues_repo.list_by_filter.return_value = []
        cursor_payload = json.dumps(
            {
                "startDate": "2026-06-01T00:00:00+00:00",
                "leagueId": "lg_prev",
            }
        )
        cursor_str = base64.b64encode(cursor_payload.encode()).decode()
        resp = client.get("/leagues", params={"cursor": cursor_str})
        assert resp.status_code == 200
        call_kwargs = mock_leagues_repo.list_by_filter.call_args.kwargs
        assert call_kwargs["cursor"] is not None
        assert call_kwargs["cursor"]["leagueId"] == "lg_prev"

    def test_invalid_cursor_returns_400(
        self, client: TestClient, mock_leagues_repo: Mock
    ):
        resp = client.get("/leagues", params={"cursor": "not-valid-base64!!!"})
        assert resp.status_code == 400

    def test_repo_called_with_limit_plus_one(
        self, client: TestClient, mock_leagues_repo: Mock
    ):
        mock_leagues_repo.list_by_filter.return_value = []
        client.get("/leagues", params={"limit": 10})
        call_kwargs = mock_leagues_repo.list_by_filter.call_args.kwargs
        assert call_kwargs["limit"] == 11  # limit + 1


class TestGetLeaguesFilters:
    def test_default_status_is_open(self, client: TestClient, mock_leagues_repo: Mock):
        mock_leagues_repo.list_by_filter.return_value = []
        client.get("/leagues")
        call_kwargs = mock_leagues_repo.list_by_filter.call_args.kwargs
        assert call_kwargs["status"] == LeagueStatusEnum.OPEN

    def test_region_filter_forwarded(self, client: TestClient, mock_leagues_repo: Mock):
        mock_leagues_repo.list_by_filter.return_value = []
        client.get("/leagues", params={"region": "athens"})
        call_kwargs = mock_leagues_repo.list_by_filter.call_args.kwargs
        assert call_kwargs["region"] == "athens"

    def test_sport_filter_forwarded(self, client: TestClient, mock_leagues_repo: Mock):
        mock_leagues_repo.list_by_filter.return_value = []
        client.get("/leagues", params={"sport": "padel"})
        call_kwargs = mock_leagues_repo.list_by_filter.call_args.kwargs
        assert call_kwargs["sport"] == SportEnum.PADEL

    def test_status_filter_forwarded(self, client: TestClient, mock_leagues_repo: Mock):
        mock_leagues_repo.list_by_filter.return_value = []
        client.get("/leagues", params={"status": "active"})
        call_kwargs = mock_leagues_repo.list_by_filter.call_args.kwargs
        assert call_kwargs["status"] == LeagueStatusEnum.ACTIVE

    def test_no_region_filter_is_none(
        self, client: TestClient, mock_leagues_repo: Mock
    ):
        mock_leagues_repo.list_by_filter.return_value = []
        client.get("/leagues")
        call_kwargs = mock_leagues_repo.list_by_filter.call_args.kwargs
        assert call_kwargs["region"] is None

    def test_no_sport_filter_is_none(self, client: TestClient, mock_leagues_repo: Mock):
        mock_leagues_repo.list_by_filter.return_value = []
        client.get("/leagues")
        call_kwargs = mock_leagues_repo.list_by_filter.call_args.kwargs
        assert call_kwargs["sport"] is None


class TestGetLeaguesValidation:
    def test_limit_too_large_returns_422(self, client: TestClient):
        resp = client.get("/leagues", params={"limit": 51})
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, client: TestClient):
        resp = client.get("/leagues", params={"limit": 0})
        assert resp.status_code == 422

    def test_invalid_sport_returns_422(self, client: TestClient):
        resp = client.get("/leagues", params={"sport": "chess"})
        assert resp.status_code == 422

    def test_invalid_status_returns_422(self, client: TestClient):
        resp = client.get("/leagues", params={"status": "unknown"})
        assert resp.status_code == 422


class TestGetLeaguesAuth:
    def test_no_auth_returns_401(self):
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/leagues")
        assert resp.status_code == 401


class TestLeagueMemberEndpoints:
    @pytest.fixture()
    def _override_role_service_admin(self):
        mock_rs = Mock()
        mock_rs.get_league_owner_uid.return_value = (
            _UID  # owner shortcut → always passes
        )
        app.dependency_overrides[get_role_service] = lambda: mock_rs
        yield mock_rs
        app.dependency_overrides.pop(get_role_service, None)

    @pytest.fixture()
    def client_admin(self, _override_auth, _override_role_service_admin):
        return TestClient(app)

    def test_add_member_returns_501(self, client_admin: TestClient):
        resp = client_admin.post("/leagues/lg1/members")
        assert resp.status_code == 501

    def test_remove_member_returns_501(self, client_admin: TestClient):
        resp = client_admin.delete("/leagues/lg1/members/user_other")
        assert resp.status_code == 501

    def test_add_member_no_auth_returns_401(self):
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post("/leagues/lg1/members")
        assert resp.status_code == 401

    def test_remove_member_no_auth_returns_401(self):
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.delete("/leagues/lg1/members/user_other")
        assert resp.status_code == 401
