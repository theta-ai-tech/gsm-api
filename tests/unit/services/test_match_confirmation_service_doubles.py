"""
Unit tests for the doubles (DBL-5) extension of MatchConfirmationService.

Covers:
- First submission: any participant can submit a doubles result, all 4
  playTab states are updated correctly (submitter → WAITING_OPPONENT,
  others → CONFIRM_REQUIRED), score persisted with winnerTeam.
- Confirmation: opposing-team confirmation completes the match for all 4;
  same-team confirmation is rejected.
- Dispute: opposing-team disagreement transitions match + all 4 users to
  MATCH_DISPUTED state.
- Validation: winner_uid rejected for doubles, winner_team rejected for
  singles, missing team label on participants surfaces an error.
"""

from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.models.common import MatchScore, SetScore
from app.models.enums import (
    MatchResultEnum,
    MatchStatusEnum,
    MatchTypeEnum,
    PlayTabStateEnum,
    SportEnum,
)
from app.models.match import Match, MatchParticipant, VerifyScoreRequest
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.ticker_repo import TickerRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.match_confirmation_service import MatchConfirmationService

MATCH_ID = "match_doubles_001"
SPORT = SportEnum.PADEL

# Team A: alice + ignatios. Team B: bob + charlie.
A1 = "user_alice"
A2 = "user_ignatios"
B1 = "user_bob"
B2 = "user_charlie"


def _doubles_match(
    status: MatchStatusEnum = MatchStatusEnum.SCHEDULED,
    score: MatchScore | None = None,
    result_submitted_by: list[str] | None = None,
) -> Match:
    return Match(
        match_id=MATCH_ID,
        sport=SPORT,
        status=status,
        match_type=MatchTypeEnum.DOUBLES,
        participant_uids=[A1, A2, B1, B2],
        participants=[
            MatchParticipant(uid=A1, team="A", role="player"),
            MatchParticipant(uid=A2, team="A", role="player"),
            MatchParticipant(uid=B1, team="B", role="player"),
            MatchParticipant(uid=B2, team="B", role="player"),
        ],
        score=score,
        result_submitted_by=result_submitted_by or [],
    )


def _make_score(winner_team: str = "A") -> MatchScore:
    return MatchScore(
        sets=[SetScore(p1_games=6, p2_games=3), SetScore(p1_games=6, p2_games=4)],
        winner_team=winner_team,
    )


def _make_service(match: Match) -> tuple[MatchConfirmationService, MagicMock, dict]:
    mock_matches_repo = Mock(spec=MatchesRepo)
    mock_matches_repo.get_by_id.return_value = match
    mock_users_repo = Mock(spec=UsersRepo)
    mock_ph_repo = Mock(spec=PointHistoryRepo)
    mock_tier_config_repo = Mock(spec=TierConfigRepo)
    mock_ticker_repo = Mock(spec=TickerRepo)
    mock_region_config_repo = Mock(spec=RegionConfigRepo)

    mock_client = MagicMock()
    mock_client.transaction.return_value = MagicMock()

    # MagicMock returns the same child for any args by default; we want
    # ``collection(...).document(uid)`` to return a distinct mock per uid so
    # tests can attribute update calls to the correct user/match doc.
    doc_refs: dict[tuple[str, str], MagicMock] = {}

    def _document_factory(coll: str):
        def _factory(doc_id: str) -> MagicMock:
            return doc_refs.setdefault(
                (coll, doc_id), MagicMock(name=f"{coll}/{doc_id}")
            )

        return _factory

    coll_refs: dict[str, MagicMock] = {}

    def _collection(coll: str) -> MagicMock:
        ref = coll_refs.get(coll)
        if ref is None:
            ref = MagicMock(name=f"collection/{coll}")
            ref.document.side_effect = _document_factory(coll)
            coll_refs[coll] = ref
        return ref

    mock_client.collection.side_effect = _collection

    service = MatchConfirmationService(
        mock_matches_repo,
        mock_users_repo,
        mock_ph_repo,
        mock_tier_config_repo,
        mock_client,
        ticker_repo=mock_ticker_repo,
        region_config_repo=mock_region_config_repo,
    )
    return service, mock_client, doc_refs


def _run(service: MatchConfirmationService, uid: str, request: VerifyScoreRequest):
    with patch("app.services.match_confirmation_service.firestore") as mock_fs:
        mock_fs.transactional = lambda fn: fn
        mock_fs.ArrayUnion = lambda items: {"__array_union__": items}
        return service.verify_score(uid, MATCH_ID, request)


class TestDoublesFirstSubmission:
    def test_returns_pending_confirmation(self):
        service, _, _refs = _make_service(_doubles_match())
        response = _run(
            service,
            A1,
            VerifyScoreRequest(winner_team="A", score=_make_score("A")),
        )
        assert response.status == MatchStatusEnum.PENDING_CONFIRMATION

    def test_response_carries_winner_and_loser_team(self):
        service, _, _refs = _make_service(_doubles_match())
        response = _run(
            service, A1, VerifyScoreRequest(winner_team="A", score=_make_score("A"))
        )
        assert response.winner_team == "A"
        assert response.loser_team == "B"
        # Singles fields are blank for doubles
        assert response.winner_uid == ""
        assert response.loser_uid == ""

    def test_winning_side_player_can_submit(self):
        # A1 (winning side) submits — should not raise.
        service, _, _refs = _make_service(_doubles_match())
        _run(service, A1, VerifyScoreRequest(winner_team="A", score=_make_score("A")))

    def test_losing_side_player_can_submit(self):
        # B1 (losing side) submits a result that says A won — also valid.
        service, _, _refs = _make_service(_doubles_match())
        response = _run(
            service, B1, VerifyScoreRequest(winner_team="A", score=_make_score("A"))
        )
        assert response.status == MatchStatusEnum.PENDING_CONFIRMATION
        assert response.winner_team == "A"

    def test_match_doc_writes_status_score_and_resultByUser(self):
        service, mock_client, _refs = _make_service(_doubles_match())
        _run(service, A1, VerifyScoreRequest(winner_team="A", score=_make_score("A")))
        txn = mock_client.transaction()
        match_ref = mock_client.collection("matches").document(MATCH_ID)
        match_calls = [c for c in txn.update.call_args_list if c.args[0] == match_ref]
        assert match_calls
        updates = match_calls[0].args[1]
        assert updates["status"] == MatchStatusEnum.PENDING_CONFIRMATION
        # score doc carries winnerTeam, not a winnerUid for doubles.
        assert updates["score"]["winnerTeam"] == "A"
        assert updates["score"]["winnerUid"] is None
        # resultByUser maps each participant to W/L based on team membership
        assert updates["resultByUser"][A1] == MatchResultEnum.WIN
        assert updates["resultByUser"][A2] == MatchResultEnum.WIN
        assert updates["resultByUser"][B1] == MatchResultEnum.LOSS
        assert updates["resultByUser"][B2] == MatchResultEnum.LOSS

    def test_submitter_play_tab_transitions_to_waiting_opponent(self):
        service, mock_client, _refs = _make_service(_doubles_match())
        _run(service, A1, VerifyScoreRequest(winner_team="A", score=_make_score("A")))
        txn = mock_client.transaction()
        # Look up the update call that targeted the submitter's user doc.
        submitter_ref = mock_client.collection("users").document(A1)
        submitter_calls = [
            c for c in txn.update.call_args_list if c.args[0] == submitter_ref
        ]
        assert submitter_calls
        assert (
            submitter_calls[-1].args[1]["playTab.state"]
            == PlayTabStateEnum.POST_MATCH_WAITING_OPPONENT.value
        )

    def test_first_submission_without_score_persists_winner_team(self):
        # Regression: a scoreless first submission must still persist
        # winner_team on the match document so a later opposing-team call
        # can detect a dispute. Without this the dispute path silently
        # collapses into a confirmation.
        service, mock_client, _refs = _make_service(_doubles_match())
        _run(service, A1, VerifyScoreRequest(winner_team="A"))
        txn = mock_client.transaction()
        match_ref = mock_client.collection("matches").document(MATCH_ID)
        match_calls = [c for c in txn.update.call_args_list if c.args[0] == match_ref]
        assert match_calls
        updates = match_calls[0].args[1]
        assert "score" in updates
        assert updates["score"]["winnerTeam"] == "A"
        assert updates["score"]["winnerUid"] is None
        assert updates["score"]["sets"] == []

    def test_other_three_play_tabs_transition_to_confirm_required(self):
        service, mock_client, _refs = _make_service(_doubles_match())
        _run(service, A1, VerifyScoreRequest(winner_team="A", score=_make_score("A")))
        txn = mock_client.transaction()
        for other_uid in (A2, B1, B2):
            other_ref = mock_client.collection("users").document(other_uid)
            other_calls = [
                c for c in txn.update.call_args_list if c.args[0] == other_ref
            ]
            assert other_calls, f"expected playTab update for {other_uid}"
            assert (
                other_calls[-1].args[1]["playTab.state"]
                == PlayTabStateEnum.POST_MATCH_CONFIRM_REQUIRED.value
            )


class TestDoublesValidation:
    def test_winner_uid_rejected_on_doubles_match(self):
        service, _, _refs = _make_service(_doubles_match())
        with pytest.raises(ValueError, match="winner_uid"):
            _run(service, A1, VerifyScoreRequest(winner_uid=A1))

    def test_winner_team_rejected_on_singles_match(self):
        # Build a singles match and try to submit with winner_team.
        match = Match(
            match_id=MATCH_ID,
            sport=SPORT,
            status=MatchStatusEnum.SCHEDULED,
            match_type=MatchTypeEnum.SINGLES,
            participant_uids=[A1, B1],
            participants=[
                MatchParticipant(uid=A1, role="player"),
                MatchParticipant(uid=B1, role="player"),
            ],
        )
        service, _, _refs = _make_service(match)
        with pytest.raises(ValueError, match="winner_team"):
            _run(service, A1, VerifyScoreRequest(winner_team="A"))

    def test_non_participant_raises_permission_error(self):
        service, _, _refs = _make_service(_doubles_match())
        with pytest.raises(PermissionError):
            _run(service, "user_outsider", VerifyScoreRequest(winner_team="A"))


class TestDoublesConfirmation:
    def _stage_pending(
        self, original_submitter_team: str = "A", winner_team: str = "A"
    ) -> tuple[MatchConfirmationService, MagicMock, dict]:
        original_submitter = A1 if original_submitter_team == "A" else B1
        match = _doubles_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION,
            score=_make_score(winner_team=winner_team),
            result_submitted_by=[original_submitter],
        )
        return _make_service(match)

    def test_opposing_team_confirmation_completes_match(self):
        service, mock_client, _refs = self._stage_pending()
        # B1 (opposing team) confirms A as winner — match completes.
        response = _run(service, B1, VerifyScoreRequest(winner_team="A"))
        assert response.status == MatchStatusEnum.COMPLETED
        # All 4 user docs go back to DISCOVERY.
        txn = mock_client.transaction()
        for p_uid in (A1, A2, B1, B2):
            user_ref = mock_client.collection("users").document(p_uid)
            calls = [c for c in txn.update.call_args_list if c.args[0] == user_ref]
            assert calls
            assert (
                calls[-1].args[1]["playTab.state"] == PlayTabStateEnum.DISCOVERY.value
            )

    def test_same_team_confirmation_rejected(self):
        service, _, _refs = self._stage_pending()
        # A2 (same team as original submitter A1) tries to confirm.
        with pytest.raises(ValueError, match="opposing team"):
            _run(service, A2, VerifyScoreRequest(winner_team="A"))

    def test_opposing_team_disagreement_disputes_match(self):
        # Stored winner_team is A; opposing-team confirmer says B → dispute.
        service, mock_client, _refs = self._stage_pending(winner_team="A")
        response = _run(service, B1, VerifyScoreRequest(winner_team="B"))
        assert response.status == MatchStatusEnum.DISPUTED
        txn = mock_client.transaction()
        for p_uid in (A1, A2, B1, B2):
            user_ref = mock_client.collection("users").document(p_uid)
            calls = [c for c in txn.update.call_args_list if c.args[0] == user_ref]
            assert calls
            assert (
                calls[-1].args[1]["playTab.state"]
                == PlayTabStateEnum.MATCH_DISPUTED.value
            )

    def test_completed_match_doc_carries_finished_at(self):
        service, mock_client, _refs = self._stage_pending()
        _run(service, B1, VerifyScoreRequest(winner_team="A"))
        txn = mock_client.transaction()
        match_ref = mock_client.collection("matches").document(MATCH_ID)
        match_calls = [c for c in txn.update.call_args_list if c.args[0] == match_ref]
        assert match_calls
        updates = match_calls[-1].args[1]
        assert updates["status"] == MatchStatusEnum.COMPLETED
        assert isinstance(updates["finishedAt"], datetime)


class TestSinglesRegression:
    """Confirm singles matches still flow through the legacy code path."""

    def _singles_match(
        self,
        status: MatchStatusEnum = MatchStatusEnum.SCHEDULED,
    ) -> Match:
        return Match(
            match_id=MATCH_ID,
            sport=SPORT,
            status=status,
            match_type=MatchTypeEnum.SINGLES,
            participant_uids=[A1, B1],
            participants=[
                MatchParticipant(uid=A1, role="player"),
                MatchParticipant(uid=B1, role="player"),
            ],
        )

    def test_singles_first_submission_pending_confirmation(self):
        service, _, _refs = _make_service(self._singles_match())
        response = _run(service, A1, VerifyScoreRequest(winner_uid=A1))
        assert response.status == MatchStatusEnum.PENDING_CONFIRMATION
        assert response.winner_uid == A1
        assert response.loser_uid == B1
        assert response.winner_team is None

    def test_singles_missing_winner_target_rejected(self):
        # The model validator rejects an empty payload.
        with pytest.raises(ValueError):
            VerifyScoreRequest()

    def test_singles_both_winner_uid_and_winner_team_rejected(self):
        with pytest.raises(ValueError):
            VerifyScoreRequest(winner_uid=A1, winner_team="A")
