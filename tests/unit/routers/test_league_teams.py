"""Unit tests for doubles team join lifecycle router endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_league_service, get_leagues_repo
from app.deps import get_current_user, get_role_service
from app.main import app
from app.models.enums import (
    LeagueFormatEnum,
    LeagueMemberStatusEnum,
    LeagueRoleEnum,
    LeagueStatusEnum,
    LeagueTeamStatusEnum,
    SportEnum,
)
from app.models.league import League, LeagueMember, LeagueTeam
from app.security import CurrentUser
from app.services.league_service import (
    LeagueService,
    LeagueTeamConflictError,
    LeagueTeamForbiddenError,
    LeagueTeamNotFoundError,
    LeagueTeamValidationError,
)

_UID = "user_captain"
_PARTNER = "user_partner"


@pytest.fixture()
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email="cap@gsm.local"
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def mock_league_service():
    svc = Mock(spec=LeagueService)
    app.dependency_overrides[get_league_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_league_service, None)


@pytest.fixture()
def mock_leagues_repo():
    repo = Mock(
        spec_set=[
            "get_by_id",
            "find_teams_for_user",
            "list_teams",
        ]
    )
    app.dependency_overrides[get_leagues_repo] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_leagues_repo, None)


@pytest.fixture()
def mock_role_service():
    svc = Mock()
    app.dependency_overrides[get_role_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_role_service, None)


@pytest.fixture()
def client(_override_auth, mock_leagues_repo, mock_league_service):
    return TestClient(app)


def _make_league(fmt: LeagueFormatEnum = LeagueFormatEnum.DOUBLES) -> League:
    return League(
        league_id="lg1",
        name="Padel Doubles",
        sport=SportEnum.PADEL,
        status=LeagueStatusEnum.OPEN,
        owner_uid="owner1",
        format=fmt,
    )


def _make_team(
    status: LeagueTeamStatusEnum = LeagueTeamStatusEnum.PENDING,
) -> LeagueTeam:
    return LeagueTeam(
        team_id="team_1",
        status=status,
        captain_uid=_UID,
        partner_uid=_PARTNER,
        member_uids=[_UID, _PARTNER],
        name="Cap / Partner",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )


def _make_member() -> LeagueMember:
    return LeagueMember(
        uid=_UID,
        role=LeagueRoleEnum.PLAYER,
        status=LeagueMemberStatusEnum.ACTIVE,
        joined_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )


class TestJoinDispatch:
    def test_singles_join_no_body(self, client, mock_leagues_repo, mock_league_service):
        mock_leagues_repo.get_by_id.return_value = _make_league(
            LeagueFormatEnum.SINGLES
        )
        mock_league_service.join_league.return_value = _make_member()
        resp = client.post("/leagues/lg1/join")
        assert resp.status_code == 201
        assert resp.json()["uid"] == _UID
        mock_league_service.invite_team.assert_not_called()

    def test_singles_join_empty_body(
        self, client, mock_leagues_repo, mock_league_service
    ):
        mock_leagues_repo.get_by_id.return_value = _make_league(
            LeagueFormatEnum.SINGLES
        )
        mock_league_service.join_league.return_value = _make_member()
        resp = client.post("/leagues/lg1/join", json={})
        assert resp.status_code == 201

    def test_singles_with_partner_returns_400(
        self, client, mock_leagues_repo, mock_league_service
    ):
        mock_leagues_repo.get_by_id.return_value = _make_league(
            LeagueFormatEnum.SINGLES
        )
        resp = client.post("/leagues/lg1/join", json={"partner_uid": _PARTNER})
        assert resp.status_code == 400
        mock_league_service.join_league.assert_not_called()

    def test_doubles_no_partner_returns_400(
        self, client, mock_leagues_repo, mock_league_service
    ):
        mock_leagues_repo.get_by_id.return_value = _make_league()
        resp = client.post("/leagues/lg1/join", json={})
        assert resp.status_code == 400
        mock_league_service.invite_team.assert_not_called()

    def test_doubles_invite_returns_201_team(
        self, client, mock_leagues_repo, mock_league_service
    ):
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_league_service.invite_team.return_value = _make_team()
        resp = client.post("/leagues/lg1/join", json={"partner_uid": _PARTNER})
        assert resp.status_code == 201
        body = resp.json()
        assert body["team_id"] == "team_1"
        assert body["status"] == "pending"
        assert body["partner_uid"] == _PARTNER
        mock_league_service.invite_team.assert_called_once_with(
            "lg1", _UID, _PARTNER, None
        )

    def test_league_not_found_returns_404(
        self, client, mock_leagues_repo, mock_league_service
    ):
        mock_leagues_repo.get_by_id.return_value = None
        resp = client.post("/leagues/lg1/join", json={"partner_uid": _PARTNER})
        assert resp.status_code == 404

    def test_invite_self_partner_maps_400(
        self, client, mock_leagues_repo, mock_league_service
    ):
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_league_service.invite_team.side_effect = LeagueTeamValidationError("bad")
        resp = client.post("/leagues/lg1/join", json={"partner_uid": _PARTNER})
        assert resp.status_code == 400

    def test_invite_partner_missing_maps_404(
        self, client, mock_leagues_repo, mock_league_service
    ):
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_league_service.invite_team.side_effect = LeagueTeamNotFoundError(
            "no partner"
        )
        resp = client.post("/leagues/lg1/join", json={"partner_uid": _PARTNER})
        assert resp.status_code == 404

    def test_invite_already_teamed_maps_409(
        self, client, mock_leagues_repo, mock_league_service
    ):
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_league_service.invite_team.side_effect = LeagueTeamConflictError("dupe")
        resp = client.post("/leagues/lg1/join", json={"partner_uid": _PARTNER})
        assert resp.status_code == 409


class TestAcceptEndpoint:
    def test_accept_returns_200(self, client, mock_league_service):
        mock_league_service.accept_team.return_value = _make_team(
            LeagueTeamStatusEnum.ACTIVE
        )
        resp = client.post("/leagues/lg1/teams/team_1/accept")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        mock_league_service.accept_team.assert_called_once_with("lg1", "team_1", _UID)

    def test_accept_non_partner_returns_403(self, client, mock_league_service):
        mock_league_service.accept_team.side_effect = LeagueTeamForbiddenError("nope")
        resp = client.post("/leagues/lg1/teams/team_1/accept")
        assert resp.status_code == 403

    def test_accept_non_pending_returns_409(self, client, mock_league_service):
        mock_league_service.accept_team.side_effect = LeagueTeamConflictError(
            "bad state"
        )
        resp = client.post("/leagues/lg1/teams/team_1/accept")
        assert resp.status_code == 409

    def test_accept_missing_returns_404(self, client, mock_league_service):
        mock_league_service.accept_team.side_effect = LeagueTeamNotFoundError("missing")
        resp = client.post("/leagues/lg1/teams/team_1/accept")
        assert resp.status_code == 404


class TestDeclineEndpoint:
    def test_decline_returns_200(self, client, mock_league_service):
        mock_league_service.decline_team.return_value = _make_team(
            LeagueTeamStatusEnum.DECLINED
        )
        resp = client.post("/leagues/lg1/teams/team_1/decline")
        assert resp.status_code == 200
        assert resp.json()["status"] == "declined"

    def test_decline_non_partner_returns_403(self, client, mock_league_service):
        mock_league_service.decline_team.side_effect = LeagueTeamForbiddenError("nope")
        resp = client.post("/leagues/lg1/teams/team_1/decline")
        assert resp.status_code == 403


class TestCancelEndpoint:
    def test_cancel_returns_200(self, client, mock_league_service):
        mock_league_service.cancel_team.return_value = _make_team(
            LeagueTeamStatusEnum.CANCELLED
        )
        resp = client.delete("/leagues/lg1/teams/team_1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_non_captain_returns_403(self, client, mock_league_service):
        mock_league_service.cancel_team.side_effect = LeagueTeamForbiddenError("nope")
        resp = client.delete("/leagues/lg1/teams/team_1")
        assert resp.status_code == 403


class TestListTeamsEndpoint:
    def test_mine_filters_to_caller(self, client, mock_leagues_repo):
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_leagues_repo.find_teams_for_user.return_value = [_make_team()]
        resp = client.get("/leagues/lg1/teams?status=pending&mine=true")
        assert resp.status_code == 200
        body = resp.json()
        assert body["league_id"] == "lg1"
        assert len(body["teams"]) == 1
        mock_leagues_repo.find_teams_for_user.assert_called_once_with(
            "lg1", _UID, [LeagueTeamStatusEnum.PENDING]
        )

    def test_mine_defaults_to_actionable_statuses(self, client, mock_leagues_repo):
        # No explicit status → declined/cancelled invites are excluded.
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_leagues_repo.find_teams_for_user.return_value = []
        resp = client.get("/leagues/lg1/teams?mine=true")
        assert resp.status_code == 200
        mock_leagues_repo.find_teams_for_user.assert_called_once_with(
            "lg1", _UID, [LeagueTeamStatusEnum.PENDING, LeagueTeamStatusEnum.ACTIVE]
        )

    def test_league_not_found_returns_404(self, client, mock_leagues_repo):
        mock_leagues_repo.get_by_id.return_value = None
        resp = client.get("/leagues/lg1/teams?mine=true")
        assert resp.status_code == 404

    def test_not_mine_requires_membership(
        self, client, mock_leagues_repo, mock_role_service
    ):
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_leagues_repo.list_teams.return_value = [_make_team()]
        resp = client.get("/leagues/lg1/teams")
        assert resp.status_code == 200
        mock_role_service.assert_not_called
        mock_leagues_repo.list_teams.assert_called_once()
