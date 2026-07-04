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
from app.services.league_service import (
    LeagueKickoffConflictError,
    LeagueService,
    RankedLeagueMember,
    split_into_divisions,
)


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
            result = league_service.join_league("lg1", "uid1", "Alice")
        assert isinstance(result, LeagueMember)
        assert result.uid == "uid1"
        assert result.role == LeagueRoleEnum.PLAYER
        assert result.status == LeagueMemberStatusEnum.ACTIVE
        assert result.stats is None
        assert result.display_name == "Alice"

    def test_join_with_no_display_name(
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league()
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            _setup_txn_mocks(mock_firestore_client, member_exists=False)
            result = league_service.join_league("lg1", "uid1")
        assert result.display_name is None

    def test_join_writes_display_name_to_firestore(
        self,
        league_service: LeagueService,
        mock_leagues_repo: Mock,
        mock_firestore_client: Mock,
    ) -> None:
        mock_leagues_repo.get_by_id.return_value = _make_league()
        txn_mock = Mock()
        mock_firestore_client.transaction.return_value = txn_mock
        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            _setup_txn_mocks(mock_firestore_client, member_exists=False)
            # The transaction object passed to _join_txn is the mock returned by client.transaction()
            league_service.join_league("lg1", "uid1", "Alice")
        # txn.set is called with member_ref and member_data containing displayName
        set_calls = mock_firestore_client.transaction.return_value.set.call_args_list
        assert len(set_calls) >= 1
        written_data = set_calls[0][0][1]
        assert written_data.get("uid") == "uid1"
        assert written_data.get("displayName") == "Alice"
        assert written_data.get("divisionId") is None

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


def _make_member_with_stats(
    uid: str,
    wins: int = 0,
    losses: int = 0,
    display_name: str | None = None,
) -> LeagueMember:
    return LeagueMember(
        uid=uid,
        role=LeagueRoleEnum.PLAYER,
        status=LeagueMemberStatusEnum.ACTIVE,
        joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        stats={"wins": wins, "losses": losses},
        display_name=display_name,
    )


def _make_ranked_member(uid: str, pts: int) -> RankedLeagueMember:
    return RankedLeagueMember(
        member=LeagueMember(
            uid=uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            stats=None,
        ),
        pts=pts,
    )


class TestSplitIntoDivisions:
    def test_four_members_stays_single_division(self) -> None:
        splits = split_into_divisions(
            [_make_ranked_member(f"u{i}", 1000 - i) for i in range(4)]
        )

        assert len(splits) == 1
        assert splits[0].division_id == "div-1"
        assert [item.member.uid for item in splits[0].members] == [
            "u0",
            "u1",
            "u2",
            "u3",
        ]

    def test_eleven_members_split_near_even_at_target_six(self) -> None:
        splits = split_into_divisions(
            [_make_ranked_member(f"u{i}", 2000 - i) for i in range(11)]
        )

        assert [len(split.members) for split in splits] == [6, 5]
        assert splits[0].rating_max == 2000
        assert splits[0].rating_min == 1995
        assert splits[1].rating_max == 1994
        assert splits[1].rating_min == 1990

    def test_exact_target_size_stays_single_division(self) -> None:
        splits = split_into_divisions(
            [_make_ranked_member(f"u{i}", 1200 - i) for i in range(6)]
        )

        assert len(splits) == 1
        assert len(splits[0].members) == 6

    def test_tied_pts_are_preserved_in_sorted_order(self) -> None:
        members = [
            _make_ranked_member("u_a", 1200),
            _make_ranked_member("u_b", 1200),
            _make_ranked_member("u_c", 1100),
            _make_ranked_member("u_d", 1100),
            _make_ranked_member("u_e", 1000),
        ]

        splits = split_into_divisions(members)

        assert [item.member.uid for item in splits[0].members] == [
            "u_a",
            "u_b",
            "u_c",
            "u_d",
            "u_e",
        ]
        assert splits[0].rating_min == 1000
        assert splits[0].rating_max == 1200

    def test_max_divisions_caps_split_count(self) -> None:
        splits = split_into_divisions(
            [_make_ranked_member(f"u{i}", 1400 - i) for i in range(18)],
            max_divisions=2,
        )

        assert [len(split.members) for split in splits] == [9, 9]


class TestKickoffLeague:
    def test_member_pts_missing_profile_or_ranking_defaults_to_zero(
        self, mock_leagues_repo: Mock, mock_firestore_client: Mock
    ) -> None:
        users_repo = Mock()
        users_repo.get_user_doc.side_effect = [
            None,
            {"rankings": {}},
            {"rankings": {"tennis": {"pts": 1240}}},
        ]
        service = LeagueService(
            mock_leagues_repo, mock_firestore_client, users_repo=users_repo
        )

        assert service._member_pts("missing", "tennis") == 0
        assert service._member_pts("unranked", "tennis") == 0
        assert service._member_pts("ranked", "tennis") == 1240

    def test_dividing_league_blocks_duplicate_kickoff_claim(
        self, mock_leagues_repo: Mock, mock_firestore_client: Mock
    ) -> None:
        league_ref = Mock()
        league_doc = Mock()
        league_doc.exists = True
        league_doc.to_dict.return_value = {"status": "dividing"}
        league_ref.get.return_value = league_doc
        mock_firestore_client.collection.return_value.document.return_value = league_ref
        mock_leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.DIVIDING
        )

        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            service = LeagueService(mock_leagues_repo, mock_firestore_client)
            with pytest.raises(LeagueKickoffConflictError, match="in progress"):
                service.kickoff_league("lg1")

        mock_leagues_repo.list_members.assert_not_called()

    def test_empty_member_pool_restores_open_status(
        self, mock_leagues_repo: Mock, mock_firestore_client: Mock
    ) -> None:
        league_ref = Mock()
        league_doc = Mock()
        league_doc.exists = True
        league_doc.to_dict.return_value = {"status": "open"}
        league_ref.get.return_value = league_doc
        mock_firestore_client.collection.return_value.document.return_value = league_ref
        mock_leagues_repo.get_by_id.return_value = _make_league()
        mock_leagues_repo.list_members.return_value = []

        with patch("app.services.league_service.firestore.transactional", lambda f: f):
            service = LeagueService(mock_leagues_repo, mock_firestore_client)
            with pytest.raises(LeagueKickoffConflictError, match="no active members"):
                service.kickoff_league("lg1")

        league_ref.update.assert_any_call({"status": LeagueStatusEnum.OPEN.value})
        mock_leagues_repo.list_members.assert_called_once_with("lg1", limit=None)


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

    def test_standings_uses_member_display_name(
        self, league_service: LeagueService, mock_leagues_repo: Mock
    ) -> None:
        mock_leagues_repo.list_members.return_value = [
            _make_member_with_stats("uid1", wins=2, losses=1, display_name="Alice")
        ]
        result = league_service.get_standings("lg1")
        assert result[0].display_name == "Alice"

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
