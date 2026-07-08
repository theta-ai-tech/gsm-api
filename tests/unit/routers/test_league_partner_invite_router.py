"""Unit tests for the partner_invite branch of POST /leagues/{id}/join."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_league_service, get_leagues_repo
from app.deps import get_current_user
from app.main import app
from app.models.enums import (
    LeagueFormatEnum,
    LeagueStatusEnum,
    LeagueTeamStatusEnum,
    SportEnum,
)
from app.models.league import League, LeagueTeam, LeagueTeamPartnerInvite
from app.security import CurrentUser
from app.services.league_service import LeagueService, LeagueTeamConflictError

_UID = "user_captain"


@pytest.fixture()
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email="cap@gsm.local", display_name="Cap"
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
    repo = Mock(spec_set=["get_by_id"])
    app.dependency_overrides[get_leagues_repo] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_leagues_repo, None)


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


def _make_placeholder_team() -> LeagueTeam:
    return LeagueTeam(
        team_id="team_1",
        status=LeagueTeamStatusEnum.ACTIVE,
        captain_uid=_UID,
        partner_uid=None,
        member_uids=[_UID, "invite:abc"],
        name="Cap / Nick",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        accepted_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        partner_placeholder_uid="invite:abc",
        partner_invite=LeagueTeamPartnerInvite(name="Nick", phone="+30123"),
    )


def test_doubles_invite_placeholder_returns_201_active_no_email(
    client, mock_leagues_repo, mock_league_service
):
    mock_leagues_repo.get_by_id.return_value = _make_league()
    mock_league_service.invite_placeholder_team.return_value = _make_placeholder_team()
    resp = client.post(
        "/leagues/lg1/join",
        json={
            "partner_invite": {
                "name": "Nick",
                "email": "nick@example.com",
                "phone": "+30123",
            }
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["partner_uid"] is None
    assert body["partner_invite"] == {"name": "Nick", "phone": "+30123"}
    mock_league_service.invite_placeholder_team.assert_called_once_with(
        "lg1", _UID, "Nick", "nick@example.com", "+30123", "Cap"
    )
    mock_league_service.invite_team.assert_not_called()


def test_partner_uid_and_invite_together_returns_422(
    client, mock_leagues_repo, mock_league_service
):
    mock_leagues_repo.get_by_id.return_value = _make_league()
    resp = client.post(
        "/leagues/lg1/join",
        json={
            "partner_uid": "x",
            "partner_invite": {"name": "Nick", "email": "n@example.com"},
        },
    )
    assert resp.status_code == 422, resp.text
    mock_league_service.invite_placeholder_team.assert_not_called()


def test_invalid_email_returns_422(client, mock_leagues_repo, mock_league_service):
    mock_leagues_repo.get_by_id.return_value = _make_league()
    resp = client.post(
        "/leagues/lg1/join",
        json={"partner_invite": {"name": "Nick", "email": "not-an-email"}},
    )
    assert resp.status_code == 422, resp.text


def test_empty_name_returns_422(client, mock_leagues_repo, mock_league_service):
    mock_leagues_repo.get_by_id.return_value = _make_league()
    resp = client.post(
        "/leagues/lg1/join",
        json={"partner_invite": {"name": "", "email": "nick@example.com"}},
    )
    assert resp.status_code == 422, resp.text


def test_singles_with_partner_invite_returns_400(
    client, mock_leagues_repo, mock_league_service
):
    mock_leagues_repo.get_by_id.return_value = _make_league(LeagueFormatEnum.SINGLES)
    resp = client.post(
        "/leagues/lg1/join",
        json={"partner_invite": {"name": "Nick", "email": "nick@example.com"}},
    )
    assert resp.status_code == 400, resp.text
    mock_league_service.invite_placeholder_team.assert_not_called()


def test_service_conflict_maps_to_409(client, mock_leagues_repo, mock_league_service):
    mock_leagues_repo.get_by_id.return_value = _make_league()
    mock_league_service.invite_placeholder_team.side_effect = LeagueTeamConflictError(
        "dup"
    )
    resp = client.post(
        "/leagues/lg1/join",
        json={"partner_invite": {"name": "Nick", "email": "nick@example.com"}},
    )
    assert resp.status_code == 409, resp.text
