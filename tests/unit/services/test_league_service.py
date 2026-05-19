from __future__ import annotations

from datetime import datetime, timezone
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
        "status": "open",
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

    def test_status_rechecked_inside_transaction(
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        """TOCTOU guard: league was OPEN at pre-check but transitions to ACTIVE before txn commit."""
        mock_leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.OPEN
        )
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            _setup_txn_mocks(mock_firestore_client, member_exists=False)
            # Override the league_doc to return "active" status — simulates TOCTOU race
            mock_league_ref = (
                mock_firestore_client.collection.return_value.document.return_value
            )
            mock_league_ref.get.return_value.to_dict.return_value = {
                "status": "active",
                "currentPlayers": 3,
                "maxPlayers": 10,
            }
            with pytest.raises(ValueError, match="active"):
                league_service.join_league("lg1", "uid1")

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
            mock_league_doc.to_dict.return_value = {
                "status": "open"
            }  # no currentPlayers/maxPlayers

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


def _make_member_with_stats(uid: str, wins: int = 0, losses: int = 0) -> LeagueMember:
    return LeagueMember(
        uid=uid,
        role=LeagueRoleEnum.PLAYER,
        status=LeagueMemberStatusEnum.ACTIVE,
        joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        stats={"wins": wins, "losses": losses},
    )


class TestGetStandings:
    def test_empty_member_list_returns_empty(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.list_members.return_value = []
        result = league_service.get_standings("lg1")
        assert result == []

    def test_single_member_gets_rank_1(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.list_members.return_value = [_make_member_with_stats("uid1")]
        result = league_service.get_standings("lg1")
        assert len(result) == 1
        assert result[0].rank == 1
        assert result[0].uid == "uid1"
        assert result[0].wins == 0
        assert result[0].losses == 0

    def test_member_with_no_stats_gets_zero(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        member = LeagueMember(
            uid="uid1",
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            stats=None,
        )
        mock_leagues_repo.list_members.return_value = [member]
        result = league_service.get_standings("lg1")
        assert result[0].wins == 0
        assert result[0].losses == 0

    def test_sort_wins_descending(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.list_members.return_value = [
            _make_member_with_stats("uid_a", wins=3, losses=0),
            _make_member_with_stats("uid_b", wins=5, losses=0),
        ]
        result = league_service.get_standings("lg1")
        assert result[0].uid == "uid_b"
        assert result[0].rank == 1
        assert result[1].uid == "uid_a"
        assert result[1].rank == 2

    def test_sort_losses_ascending_for_same_wins(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.list_members.return_value = [
            _make_member_with_stats("uid_a", wins=3, losses=5),
            _make_member_with_stats("uid_b", wins=3, losses=2),
        ]
        result = league_service.get_standings("lg1")
        assert result[0].uid == "uid_b"
        assert result[0].rank == 1
        assert result[1].uid == "uid_a"
        assert result[1].rank == 2

    def test_tied_members_share_rank(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.list_members.return_value = [
            _make_member_with_stats("uid_a", wins=3, losses=2),
            _make_member_with_stats("uid_b", wins=3, losses=2),
        ]
        result = league_service.get_standings("lg1")
        assert result[0].rank == 1
        assert result[1].rank == 1

    def test_dense_ranking_after_tie(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.list_members.return_value = [
            _make_member_with_stats("uid_a", wins=3, losses=2),
            _make_member_with_stats("uid_b", wins=3, losses=2),
            _make_member_with_stats("uid_c", wins=1, losses=0),
        ]
        result = league_service.get_standings("lg1")
        ranks = [e.rank for e in result]
        assert ranks[0] == 1
        assert ranks[1] == 1
        assert ranks[2] == 2  # dense: 2 not 3

    def test_display_name_falls_back_to_uid(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.list_members.return_value = [
            _make_member_with_stats("uid1", wins=2, losses=1)
        ]
        result = league_service.get_standings("lg1")
        assert result[0].display_name == "uid1"

    def test_alphabetical_tiebreak_within_tied_group(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.list_members.return_value = [
            _make_member_with_stats("zara_uid", wins=2, losses=1),
            _make_member_with_stats("anna_uid", wins=2, losses=1),
        ]
        result = league_service.get_standings("lg1")
        # Both rank 1; "anna_uid" sorts before "zara_uid" alphabetically
        assert result[0].uid == "anna_uid"
        assert result[1].uid == "zara_uid"
        assert result[0].rank == 1
        assert result[1].rank == 1
