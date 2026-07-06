from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from app.models.enums import (
    LeagueFormatEnum,
    LeagueStatusEnum,
    LeagueTeamStatusEnum,
    PlayNotificationIntentTypeEnum,
    SportEnum,
)
from app.models.league import League, LeagueTeam
from app.repos.leagues_repo import LeaguesRepo
from app.repos.notification_intent_repo import NotificationIntentRepo
from app.repos.users_repo import UsersRepo
from app.services.league_service import (
    LeagueService,
    LeagueTeamConflictError,
    LeagueTeamForbiddenError,
    LeagueTeamNotFoundError,
    LeagueTeamValidationError,
)

_CAPTAIN = "user_captain"
_PARTNER = "user_partner"


def _make_league(**kwargs) -> League:
    defaults: dict = dict(
        league_id="lg1",
        name="Padel Doubles",
        sport=SportEnum.PADEL,
        status=LeagueStatusEnum.OPEN,
        owner_uid="owner1",
        format=LeagueFormatEnum.DOUBLES,
        max_players=10,
        current_players=2,
    )
    defaults.update(kwargs)
    return League(**defaults)


def _make_team(**kwargs) -> LeagueTeam:
    defaults: dict = dict(
        team_id="team_1",
        status=LeagueTeamStatusEnum.PENDING,
        captain_uid=_CAPTAIN,
        partner_uid=_PARTNER,
        member_uids=[_CAPTAIN, _PARTNER],
        name="Captain / Partner",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return LeagueTeam(**defaults)


def _build_client(
    league_data: dict | None,
    team_data: dict | None = None,
    member_exists: dict[str, bool] | None = None,
    auto_team_id: str = "team_new",
) -> tuple[Mock, Mock, Mock]:
    """Return (client, txn, team_ref) with a path-aware Firestore mock."""
    member_exists = member_exists or {}

    client = Mock()
    txn = Mock()
    client.transaction.return_value = txn

    league_ref = Mock()
    league_doc = Mock()
    league_doc.exists = league_data is not None
    league_doc.to_dict.return_value = league_data or {}
    league_ref.get.return_value = league_doc

    team_ref = Mock()
    team_ref.id = auto_team_id
    team_doc = Mock()
    team_doc.exists = team_data is not None
    team_doc.to_dict.return_value = team_data or {}
    team_ref.get.return_value = team_doc

    teams_col = Mock()
    teams_col.document.side_effect = lambda team_id=None: team_ref

    def _members_document(uid: str) -> Mock:
        m_ref = Mock()
        m_doc = Mock()
        m_doc.exists = member_exists.get(uid, False)
        m_doc.to_dict.return_value = {}
        m_ref.get.return_value = m_doc
        return m_ref

    members_col = Mock()
    members_col.document.side_effect = _members_document

    def _league_collection(name: str) -> Mock:
        if name == "teams":
            return teams_col
        if name == "members":
            return members_col
        return Mock()

    league_ref.collection.side_effect = _league_collection

    def _top_collection(name: str) -> Mock:
        col = Mock()
        col.document.return_value = league_ref
        return col

    client.collection.side_effect = _top_collection
    return client, txn, team_ref


def _make_service(
    leagues_repo: Mock,
    client: Mock,
    users_repo: Mock,
    notif_repo: Mock | None = None,
) -> LeagueService:
    return LeagueService(
        leagues_repo,
        client,
        users_repo=users_repo,
        divisions_repo=Mock(),
        notification_intent_repo=notif_repo,
    )


@pytest.fixture
def leagues_repo() -> Mock:
    repo = Mock(spec=LeaguesRepo)
    repo.get_member.return_value = None
    repo.find_teams_for_user.return_value = []
    return repo


@pytest.fixture
def users_repo() -> Mock:
    repo = Mock(spec=UsersRepo)
    repo.get_user_doc.side_effect = lambda uid: {
        _CAPTAIN: {"name": "Cap Tain"},
        _PARTNER: {"name": "Part Ner"},
    }.get(uid)
    return repo


@pytest.fixture
def notif_repo() -> Mock:
    return Mock(spec=NotificationIntentRepo)


_TXN_PATCH = "app.services.league_service.firestore.transactional"


class TestInviteTeam:
    def test_league_not_found_raises_404(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_by_id.return_value = None
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamNotFoundError):
            svc.invite_team("lg1", _CAPTAIN, _PARTNER)

    def test_singles_league_raises_400(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_by_id.return_value = _make_league(
            format=LeagueFormatEnum.SINGLES
        )
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamValidationError):
            svc.invite_team("lg1", _CAPTAIN, _PARTNER)

    def test_closed_league_raises_409(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_by_id.return_value = _make_league(
            status=LeagueStatusEnum.ACTIVE
        )
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamConflictError):
            svc.invite_team("lg1", _CAPTAIN, _PARTNER)

    def test_self_partner_raises_400(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_by_id.return_value = _make_league()
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamValidationError):
            svc.invite_team("lg1", _CAPTAIN, _CAPTAIN)

    def test_partner_not_found_raises_404(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_by_id.return_value = _make_league()
        users_repo.get_user_doc.side_effect = lambda uid: None
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamNotFoundError):
            svc.invite_team("lg1", _CAPTAIN, _PARTNER)

    def test_captain_already_member_raises_409(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_by_id.return_value = _make_league()
        leagues_repo.get_member.side_effect = (
            lambda lid, uid: Mock() if uid == _CAPTAIN else None
        )
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamConflictError):
            svc.invite_team("lg1", _CAPTAIN, _PARTNER)

    def test_partner_already_teamed_raises_409(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_by_id.return_value = _make_league()
        leagues_repo.find_teams_for_user.side_effect = (
            lambda lid, uid, statuses: [_make_team()] if uid == _PARTNER else []
        )
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamConflictError):
            svc.invite_team("lg1", _CAPTAIN, _PARTNER)

    def test_happy_path_creates_pending_team_and_emits_intent(
        self, leagues_repo, users_repo, notif_repo
    ) -> None:
        leagues_repo.get_by_id.return_value = _make_league()
        client, txn, team_ref = _build_client(
            {"status": "open", "currentPlayers": 2, "maxPlayers": 10}
        )
        svc = _make_service(leagues_repo, client, users_repo, notif_repo)
        with patch(_TXN_PATCH, lambda f: f):
            result = svc.invite_team("lg1", _CAPTAIN, _PARTNER, "Cap Tain")

        assert result.status == LeagueTeamStatusEnum.PENDING
        assert result.captain_uid == _CAPTAIN
        assert result.partner_uid == _PARTNER
        assert result.name == "Cap Tain / Part Ner"
        assert result.member_uids == [_CAPTAIN, _PARTNER]

        # team doc written, no member docs, no currentPlayers change
        txn.set.assert_called_once()
        written = txn.set.call_args[0][1]
        assert written["status"] == LeagueTeamStatusEnum.PENDING.value
        assert written["memberUids"] == [_CAPTAIN, _PARTNER]
        txn.update.assert_not_called()

        notif_repo.add_intent.assert_called_once()
        intent = notif_repo.add_intent.call_args[0][0]
        assert intent.type == PlayNotificationIntentTypeEnum.LEAGUE_TEAM_INVITE
        assert intent.target_uid == _PARTNER

    def test_intent_failure_is_non_fatal(
        self, leagues_repo, users_repo, notif_repo
    ) -> None:
        leagues_repo.get_by_id.return_value = _make_league()
        client, _txn, _ref = _build_client(
            {"status": "open", "currentPlayers": 2, "maxPlayers": 10}
        )
        notif_repo.add_intent.side_effect = RuntimeError("boom")
        svc = _make_service(leagues_repo, client, users_repo, notif_repo)
        with patch(_TXN_PATCH, lambda f: f):
            result = svc.invite_team("lg1", _CAPTAIN, _PARTNER)
        assert result.status == LeagueTeamStatusEnum.PENDING


class TestAcceptTeam:
    def _team_data(self, status: str = "pending") -> dict:
        return {
            "status": status,
            "captainUid": _CAPTAIN,
            "partnerUid": _PARTNER,
            "memberUids": [_CAPTAIN, _PARTNER],
            "name": "Cap Tain / Part Ner",
            "createdAt": datetime(2026, 6, 1, tzinfo=timezone.utc),
        }

    def test_team_not_found_raises_404(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = None
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamNotFoundError):
            svc.accept_team("lg1", "team_1", _PARTNER)

    def test_non_partner_raises_403(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team()
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamForbiddenError):
            svc.accept_team("lg1", "team_1", "someone_else")

    def test_non_pending_raises_409(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team()
        leagues_repo.get_by_id.return_value = _make_league()
        client, _txn, _ref = _build_client(
            {"status": "open", "currentPlayers": 2, "maxPlayers": 10},
            team_data=self._team_data(status="active"),
        )
        svc = _make_service(leagues_repo, client, users_repo)
        with patch(_TXN_PATCH, lambda f: f):
            with pytest.raises(LeagueTeamConflictError):
                svc.accept_team("lg1", "team_1", _PARTNER)

    def test_league_closed_raises_409(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team()
        leagues_repo.get_by_id.return_value = _make_league()
        client, _txn, _ref = _build_client(
            {"status": "active", "currentPlayers": 2, "maxPlayers": 10},
            team_data=self._team_data(),
        )
        svc = _make_service(leagues_repo, client, users_repo)
        with patch(_TXN_PATCH, lambda f: f):
            with pytest.raises(LeagueTeamConflictError):
                svc.accept_team("lg1", "team_1", _PARTNER)

    def test_full_capacity_raises_409(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team()
        leagues_repo.get_by_id.return_value = _make_league()
        client, _txn, _ref = _build_client(
            {"status": "open", "currentPlayers": 9, "maxPlayers": 10},
            team_data=self._team_data(),
        )
        svc = _make_service(leagues_repo, client, users_repo)
        with patch(_TXN_PATCH, lambda f: f):
            with pytest.raises(LeagueTeamConflictError):
                svc.accept_team("lg1", "team_1", _PARTNER)

    def test_exact_capacity_fit_succeeds(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team()
        leagues_repo.get_by_id.return_value = _make_league()
        client, txn, _ref = _build_client(
            {"status": "open", "currentPlayers": 8, "maxPlayers": 10},
            team_data=self._team_data(),
        )
        svc = _make_service(leagues_repo, client, users_repo)
        with patch(_TXN_PATCH, lambda f: f):
            result = svc.accept_team("lg1", "team_1", _PARTNER)
        assert result.status == LeagueTeamStatusEnum.ACTIVE

    def test_happy_path_creates_two_members_and_increments(
        self, leagues_repo, users_repo, notif_repo
    ) -> None:
        leagues_repo.get_team.return_value = _make_team()
        leagues_repo.get_by_id.return_value = _make_league()
        client, txn, _ref = _build_client(
            {"status": "open", "currentPlayers": 2, "maxPlayers": 10},
            team_data=self._team_data(),
        )
        svc = _make_service(leagues_repo, client, users_repo, notif_repo)
        with patch(_TXN_PATCH, lambda f: f):
            result = svc.accept_team("lg1", "team_1", _PARTNER)

        assert result.status == LeagueTeamStatusEnum.ACTIVE
        assert result.accepted_at is not None

        # two member docs set
        assert txn.set.call_count == 2
        written = [call.args[1] for call in txn.set.call_args_list]
        team_ids = {w["teamId"] for w in written}
        partners = {w["partnerUid"] for w in written}
        assert team_ids == {"team_1"}
        assert partners == {_CAPTAIN, _PARTNER}
        for w in written:
            assert w["status"] == "active"

        # team activated + currentPlayers += 2
        update_calls = [call.args[1] for call in txn.update.call_args_list]
        assert any("currentPlayers" in u for u in update_calls)
        assert any(
            u.get("status") == "active" and "acceptedAt" in u for u in update_calls
        )

        notif_repo.add_intent.assert_called_once()
        intent = notif_repo.add_intent.call_args[0][0]
        assert intent.type == PlayNotificationIntentTypeEnum.LEAGUE_TEAM_INVITE_ACCEPTED
        assert intent.target_uid == _CAPTAIN


class TestDeclineTeam:
    def test_team_not_found_raises_404(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = None
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamNotFoundError):
            svc.decline_team("lg1", "team_1", _PARTNER)

    def test_non_partner_raises_403(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team()
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamForbiddenError):
            svc.decline_team("lg1", "team_1", "someone_else")

    def test_non_pending_raises_409(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team(
            status=LeagueTeamStatusEnum.ACTIVE
        )
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamConflictError):
            svc.decline_team("lg1", "team_1", _PARTNER)

    def test_happy_path_sets_declined_and_notifies_captain(
        self, leagues_repo, users_repo, notif_repo
    ) -> None:
        leagues_repo.get_team.return_value = _make_team()
        leagues_repo.get_by_id.return_value = _make_league()
        team_ref = Mock()
        client = Mock()
        client.collection.return_value.document.return_value.collection.return_value.document.return_value = team_ref
        svc = _make_service(leagues_repo, client, users_repo, notif_repo)
        result = svc.decline_team("lg1", "team_1", _PARTNER)

        assert result.status == LeagueTeamStatusEnum.DECLINED
        team_ref.update.assert_called_once_with({"status": "declined"})
        notif_repo.add_intent.assert_called_once()
        intent = notif_repo.add_intent.call_args[0][0]
        assert intent.type == PlayNotificationIntentTypeEnum.LEAGUE_TEAM_INVITE_DECLINED
        assert intent.target_uid == _CAPTAIN


class TestCancelTeam:
    def test_team_not_found_raises_404(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = None
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamNotFoundError):
            svc.cancel_team("lg1", "team_1", _CAPTAIN)

    def test_non_captain_raises_403(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team()
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamForbiddenError):
            svc.cancel_team("lg1", "team_1", _PARTNER)

    def test_non_pending_raises_409(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team(
            status=LeagueTeamStatusEnum.ACTIVE
        )
        svc = _make_service(leagues_repo, Mock(), users_repo)
        with pytest.raises(LeagueTeamConflictError):
            svc.cancel_team("lg1", "team_1", _CAPTAIN)

    def test_happy_path_sets_cancelled(self, leagues_repo, users_repo) -> None:
        leagues_repo.get_team.return_value = _make_team()
        team_ref = Mock()
        client = Mock()
        client.collection.return_value.document.return_value.collection.return_value.document.return_value = team_ref
        svc = _make_service(leagues_repo, client, users_repo)
        result = svc.cancel_team("lg1", "team_1", _CAPTAIN)

        assert result.status == LeagueTeamStatusEnum.CANCELLED
        team_ref.update.assert_called_once_with({"status": "cancelled"})
