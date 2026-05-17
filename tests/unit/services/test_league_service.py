from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from app.models.league import League, LeagueMember
from app.models.enums import (
    LeagueMemberStatusEnum,
    LeagueRoleEnum,
    LeagueStatusEnum,
    SportEnum,
)
from app.repos.leagues_repo import LeaguesRepo
from app.services.league_service import LeagueService


@pytest.fixture
def mock_leagues_repo() -> Mock:
    return Mock(spec=LeaguesRepo)


@pytest.fixture
def mock_firestore_client() -> Mock:
    client = Mock()
    client.transaction.return_value = Mock()
    return client


@pytest.fixture
def league_service(
    mock_leagues_repo: Mock, mock_firestore_client: Mock
) -> LeagueService:
    return LeagueService(mock_leagues_repo, mock_firestore_client)


def _make_league(**kwargs) -> League:
    defaults: dict = dict(
        league_id="lg1",
        name="Test League",
        sport=SportEnum.TENNIS,
        status=LeagueStatusEnum.OPEN,
        owner_uid="owner1",
        max_players=10,
        current_players=3,
    )
    defaults.update(kwargs)
    return League(**defaults)


class TestJoinLeague:
    def test_league_not_found_raises(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = None
        with pytest.raises(ValueError, match="not found"):
            league_service.join_league("lg1", "uid1")

    def test_active_league_raises(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.ACTIVE
        )
        with pytest.raises(ValueError, match="ACTIVE"):
            league_service.join_league("lg1", "uid1")

    def test_completed_league_raises(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.COMPLETED
        )
        with pytest.raises(ValueError, match="COMPLETED"):
            league_service.join_league("lg1", "uid1")

    def test_duplicate_member_raises(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        existing = Mock()
        existing.uid = "uid1"
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_leagues_repo.list_members.return_value = [existing]
        with pytest.raises(ValueError, match="already a member"):
            league_service.join_league("lg1", "uid1")

    def test_full_capacity_raises(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league(
            max_players=5, current_players=5
        )
        mock_leagues_repo.list_members.return_value = []
        with pytest.raises(ValueError, match="full capacity"):
            league_service.join_league("lg1", "uid1")

    def test_happy_path_returns_league_member(
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_leagues_repo.list_members.return_value = []
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            result = league_service.join_league("lg1", "uid1")
        assert isinstance(result, LeagueMember)
        assert result.uid == "uid1"
        assert result.role == LeagueRoleEnum.PLAYER
        assert result.status == LeagueMemberStatusEnum.ACTIVE
        assert result.stats is None

    def test_open_league_can_join(
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.OPEN
        )
        mock_leagues_repo.list_members.return_value = []
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            result = league_service.join_league("lg1", "uid1")
        assert result.uid == "uid1"

    def test_upcoming_league_can_join(
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.UPCOMING
        )
        mock_leagues_repo.list_members.return_value = []
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            result = league_service.join_league("lg1", "uid1")
        assert result.uid == "uid1"

    def test_no_max_players_allows_join(
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league(
            max_players=None, current_players=None
        )
        mock_leagues_repo.list_members.return_value = []
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            result = league_service.join_league("lg1", "uid1")
        assert result.uid == "uid1"
