from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from app.models.enums import (
    LeagueFormatEnum,
    LeagueStatusEnum,
    LeagueTeamStatusEnum,
    SportEnum,
)
from app.models.league import DivisionConfig, League, LeagueMember, LeagueTeam
from app.models.enums import LeagueMemberStatusEnum, LeagueRoleEnum
from app.repos.leagues_repo import LeaguesRepo
from app.repos.users_repo import UsersRepo
from app.services.league_service import (
    LeagueKickoffConflictError,
    LeagueService,
    RankedLeagueTeam,
    split_into_divisions,
)


def _make_league(**kwargs) -> League:
    defaults: dict = dict(
        league_id="lg1",
        name="Padel Doubles",
        sport=SportEnum.PADEL,
        status=LeagueStatusEnum.OPEN,
        owner_uid="owner1",
        format=LeagueFormatEnum.DOUBLES,
        max_players=24,
        current_players=12,
    )
    defaults.update(kwargs)
    return League(**defaults)


def _make_team(team_id: str, captain: str, partner: str, **kwargs) -> LeagueTeam:
    defaults: dict = dict(
        team_id=team_id,
        status=LeagueTeamStatusEnum.ACTIVE,
        captain_uid=captain,
        partner_uid=partner,
        member_uids=[captain, partner],
        name=f"{captain} / {partner}",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return LeagueTeam(**defaults)


def _make_member(uid: str, **kwargs) -> LeagueMember:
    defaults: dict = dict(
        uid=uid,
        role=LeagueRoleEnum.PLAYER,
        status=LeagueMemberStatusEnum.ACTIVE,
        joined_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return LeagueMember(**defaults)


def _make_service(
    leagues_repo: Mock, users_repo: Mock, client: Mock | None = None
) -> LeagueService:
    return LeagueService(
        leagues_repo,
        client or Mock(),
        users_repo=users_repo,
        divisions_repo=Mock(),
    )


@pytest.fixture
def leagues_repo() -> Mock:
    return Mock(spec=LeaguesRepo)


@pytest.fixture
def users_repo() -> Mock:
    return Mock(spec=UsersRepo)


def _pts_doc(pts: int) -> dict:
    return {"rankings": {"padel": {"pts": pts}}}


class TestTeamPts:
    def test_team_pts_is_integer_mean_of_partners(
        self, leagues_repo, users_repo
    ) -> None:
        users_repo.get_user_doc.side_effect = lambda uid: {
            "u1": _pts_doc(1500),
            "u2": _pts_doc(1201),
        }.get(uid)
        svc = _make_service(leagues_repo, users_repo)
        team = _make_team("t1", "u1", "u2")
        assert svc._team_pts(team, "padel") == 1350  # (1500 + 1201) // 2

    def test_missing_ranking_counts_as_zero(self, leagues_repo, users_repo) -> None:
        users_repo.get_user_doc.side_effect = lambda uid: {
            "u1": _pts_doc(1000),
        }.get(uid)
        svc = _make_service(leagues_repo, users_repo)
        team = _make_team("t1", "u1", "u2")
        assert svc._team_pts(team, "padel") == 500


class TestSplitIntoDivisionsTeams:
    def test_teams_are_the_split_unit(self) -> None:
        ranked = [
            RankedLeagueTeam(team=_make_team(f"t{i}", f"a{i}", f"b{i}"), pts=1000 - i)
            for i in range(6)
        ]
        splits = split_into_divisions(ranked, target_size=3)
        assert len(splits) == 2
        # Highest-rated teams land in div-1; each team is intact (never split).
        assert [item.team.team_id for item in splits[0].members] == ["t0", "t1", "t2"]
        assert [item.team.team_id for item in splits[1].members] == ["t3", "t4", "t5"]


class TestDoublesKickoff:
    def _run_kickoff(
        self,
        leagues_repo: Mock,
        users_repo: Mock,
        teams: list[LeagueTeam],
        league: League | None = None,
    ):
        leagues_repo.get_by_id.return_value = league or _make_league()
        leagues_repo.list_teams.return_value = teams
        client = Mock()
        svc = _make_service(leagues_repo, users_repo, client)
        captured: list[tuple] = []
        with (
            patch.object(LeagueService, "_claim_kickoff", return_value=False),
            patch.object(
                LeagueService,
                "_commit_batched",
                side_effect=lambda self_writes: captured.extend(self_writes),
            ),
        ):
            result = svc.kickoff_league("lg1")
        return result, captured, client

    def test_no_active_teams_restores_open_and_raises(
        self, leagues_repo, users_repo
    ) -> None:
        leagues_repo.get_by_id.return_value = _make_league()
        leagues_repo.list_teams.return_value = []
        client = Mock()
        svc = _make_service(leagues_repo, users_repo, client)
        with patch.object(LeagueService, "_claim_kickoff", return_value=False):
            with pytest.raises(LeagueKickoffConflictError):
                svc.kickoff_league("lg1")
        client.collection.return_value.document.return_value.update.assert_called_once_with(
            {"status": LeagueStatusEnum.OPEN.value}
        )

    def test_seeds_by_average_and_stamps_team_and_members(
        self, leagues_repo, users_repo
    ) -> None:
        # 6 teams, targetSize 3 → 2 divisions. Ratings descend by team index.
        pts_by_uid = {}
        teams = []
        for i in range(6):
            captain, partner = f"cap{i}", f"par{i}"
            pts_by_uid[captain] = 1200 - 100 * i
            pts_by_uid[partner] = 1000 - 100 * i
            teams.append(_make_team(f"t{i}", captain, partner))
        users_repo.get_user_doc.side_effect = lambda uid: _pts_doc(
            pts_by_uid.get(uid, 0)
        )
        league = _make_league(division_config=DivisionConfig(target_size=3))

        result, captured, client = self._run_kickoff(
            leagues_repo, users_repo, teams, league
        )

        assert result.already_kicked_off is False
        assert len(result.divisions) == 2
        # Division player counts are 2× teams.
        assert [d.current_players for d in result.divisions] == [6, 6]
        # Rating ranges reflect team averages: team i avg = 1100 - 100*i.
        assert result.divisions[0].rating_range.max == 1100
        assert result.divisions[0].rating_range.min == 900
        assert result.divisions[1].rating_range.max == 800
        assert result.divisions[1].rating_range.min == 600

        # Assignment writes: each unassigned team gets a divisionId write on
        # the team doc AND both member docs (2 divisions + 6*(1+2) = 20 writes).
        division_writes = [w for w in captured if "divisionId" not in w[1]]
        assignment_writes = [w for w in captured if "divisionId" in w[1]]
        assert len(division_writes) == 2
        assert len(assignment_writes) == 18

        # Teammates always share the divisionId written to their member docs.
        div_by_ref_data: dict[str, list[str]] = {}
        for _ref, data in assignment_writes:
            div_by_ref_data.setdefault(data["divisionId"], []).append(
                data["divisionId"]
            )
        assert set(div_by_ref_data) == {"div-1", "div-2"}
        # 3 teams × 3 writes each per division
        assert all(len(v) == 9 for v in div_by_ref_data.values())

    def test_already_assigned_team_is_skipped(self, leagues_repo, users_repo) -> None:
        users_repo.get_user_doc.side_effect = lambda uid: _pts_doc(1000)
        teams = [
            _make_team("t0", "a0", "b0", division_id="div-1"),
            _make_team("t1", "a1", "b1"),
        ]
        result, captured, _client = self._run_kickoff(leagues_repo, users_repo, teams)
        assignment_writes = [w for w in captured if "divisionId" in w[1]]
        # Only the unassigned team produces writes: 1 team doc + 2 member docs.
        assert len(assignment_writes) == 3


class TestDoublesStandings:
    def test_rows_are_teams_with_captain_stats(self, leagues_repo, users_repo) -> None:
        league = _make_league(status=LeagueStatusEnum.ACTIVE)
        leagues_repo.get_by_id.return_value = league
        teams = [
            _make_team("t1", "cap1", "par1"),
            _make_team("t2", "cap2", "par2"),
        ]
        leagues_repo.list_teams.return_value = teams
        leagues_repo.list_members.return_value = [
            _make_member("cap1", stats={"wins": 3, "losses": 1}),
            _make_member("par1", stats={"wins": 3, "losses": 1}),
            _make_member("cap2", stats={"wins": 5, "losses": 0}),
            _make_member("par2", stats={"wins": 5, "losses": 0}),
        ]
        svc = _make_service(leagues_repo, users_repo)

        standings = svc.get_standings("lg1")

        assert [e.team_id for e in standings] == ["t2", "t1"]
        assert standings[0].rank == 1
        assert standings[0].uid == "cap2"
        assert standings[0].display_name == "cap2 / par2"
        assert standings[0].wins == 5
        assert standings[0].member_uids == ["cap2", "par2"]
        assert standings[1].rank == 2
        leagues_repo.list_teams.assert_called_once_with(
            "lg1", status=LeagueTeamStatusEnum.ACTIVE
        )

    def test_missing_captain_member_falls_back_to_partner_stats(
        self, leagues_repo, users_repo
    ) -> None:
        leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.ACTIVE
        )
        leagues_repo.list_teams.return_value = [_make_team("t1", "cap1", "par1")]
        leagues_repo.list_members.return_value = [
            _make_member("par1", stats={"wins": 2, "losses": 2}),
        ]
        svc = _make_service(leagues_repo, users_repo)
        standings = svc.get_standings("lg1")
        assert standings[0].wins == 2
        assert standings[0].losses == 2

    def test_tied_teams_share_rank_dense(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.ACTIVE
        )
        leagues_repo.list_teams.return_value = [
            _make_team("t1", "a1", "b1"),
            _make_team("t2", "a2", "b2"),
            _make_team("t3", "a3", "b3"),
        ]
        leagues_repo.list_members.return_value = [
            _make_member("a1", stats={"wins": 4, "losses": 0}),
            _make_member("a2", stats={"wins": 4, "losses": 0}),
            _make_member("a3", stats={"wins": 1, "losses": 3}),
        ]
        svc = _make_service(leagues_repo, users_repo)
        standings = svc.get_standings("lg1")
        assert [e.rank for e in standings] == [1, 1, 2]

    def test_division_standings_filters_by_team_division(
        self, leagues_repo, users_repo
    ) -> None:
        leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.ACTIVE
        )
        leagues_repo.list_teams.return_value = [
            _make_team("t1", "a1", "b1", division_id="div-1"),
            _make_team("t2", "a2", "b2", division_id="div-2"),
        ]
        leagues_repo.list_members.return_value = [
            _make_member("a1", stats={"wins": 1, "losses": 0}),
            _make_member("a2", stats={"wins": 2, "losses": 0}),
        ]
        svc = _make_service(leagues_repo, users_repo)
        standings = svc.get_division_standings("lg1", "div-1")
        assert [e.team_id for e in standings] == ["t1"]

    def test_singles_league_keeps_member_rows(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_by_id.return_value = _make_league(
            format=LeagueFormatEnum.SINGLES, sport=SportEnum.TENNIS
        )
        leagues_repo.list_members.return_value = [
            _make_member("u1", stats={"wins": 1, "losses": 0}, display_name="One"),
        ]
        svc = _make_service(leagues_repo, users_repo)
        standings = svc.get_standings("lg1")
        assert standings[0].uid == "u1"
        assert standings[0].team_id is None
        leagues_repo.list_teams.assert_not_called()
