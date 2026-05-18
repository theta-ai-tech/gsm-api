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


def _setup_txn_mocks(
    mock_firestore_client: Mock,
    member_exists: bool,
    current_players: int = 3,
    max_players: int = 10,
) -> None:
    """Configure mock client chain for _join_txn reads."""
    mock_member_doc = Mock()
    mock_member_doc.exists = member_exists

    mock_league_doc = Mock()
    mock_league_doc.exists = True
    mock_league_doc.to_dict.return_value = {
        "currentPlayers": current_players,
        "maxPlayers": max_players,
    }

    # The member ref chain: client.collection("leagues").document(id).collection("members").document(uid)
    mock_member_ref = Mock()
    mock_member_ref.get.return_value = mock_member_doc

    # The league ref chain: client.collection("leagues").document(id)
    mock_league_ref = Mock()
    mock_league_ref.get.return_value = mock_league_doc
    mock_league_ref.collection.return_value.document.return_value = mock_member_ref

    mock_firestore_client.collection.return_value.document.return_value = (
        mock_league_ref
    )


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
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league()
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            _setup_txn_mocks(mock_firestore_client, member_exists=True)
            with pytest.raises(ValueError, match="already a member"):
                league_service.join_league("lg1", "uid1")

    def test_full_capacity_raises(
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league(
            max_players=5, current_players=5
        )
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            _setup_txn_mocks(
                mock_firestore_client,
                member_exists=False,
                current_players=5,
                max_players=5,
            )
            with pytest.raises(ValueError, match="full capacity"):
                league_service.join_league("lg1", "uid1")

    def test_happy_path_returns_league_member(
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league()
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            _setup_txn_mocks(mock_firestore_client, member_exists=False)
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
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            _setup_txn_mocks(mock_firestore_client, member_exists=False)
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
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            _setup_txn_mocks(mock_firestore_client, member_exists=False)
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
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            mock_member_doc = Mock()
            mock_member_doc.exists = False

            mock_league_doc = Mock()
            mock_league_doc.exists = True
            mock_league_doc.to_dict.return_value = {}  # no currentPlayers/maxPlayers

            mock_member_ref = Mock()
            mock_member_ref.get.return_value = mock_member_doc

            mock_league_ref = Mock()
            mock_league_ref.get.return_value = mock_league_doc
            mock_league_ref.collection.return_value.document.return_value = (
                mock_member_ref
            )

            mock_firestore_client.collection.return_value.document.return_value = (
                mock_league_ref
            )

            result = league_service.join_league("lg1", "uid1")
        assert result.uid == "uid1"
