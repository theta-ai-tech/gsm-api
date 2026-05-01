"""
Integration tests for doubles score logging (DBL-5).

Exercises ``MatchConfirmationService.verify_score`` against a real
Firestore emulator with a seeded doubles match (4 participants, teams A/B).

Covers:
- First submission: any of the 4 participants can submit; submitter goes to
  POST_MATCH_WAITING_OPPONENT, the other 3 go to POST_MATCH_CONFIRM_REQUIRED.
- Opposing-team confirmation completes the match for all 4.
- Same-team confirmation is rejected.
- Opposing-team disagreement transitions all 4 to MATCH_DISPUTED.

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. via ``make emu-all``).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.common import MatchScore, SetScore
from app.models.enums import MatchStatusEnum, PlayTabStateEnum
from app.models.match import VerifyScoreRequest
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.match_confirmation_service import MatchConfirmationService

pytestmark = [pytest.mark.integration]

_NOW = datetime.now(timezone.utc)
_MATCH_ID = "match_doubles_int"

# Team A: a1 + a2. Team B: b1 + b2.
_A1 = "dbl5_a1"
_A2 = "dbl5_a2"
_B1 = "dbl5_b1"
_B2 = "dbl5_b2"
_ALL = (_A1, _A2, _B1, _B2)


def _make_service(db) -> MatchConfirmationService:
    return MatchConfirmationService(
        matches_repo=MatchesRepo(db),
        users_repo=UsersRepo(db),
        point_history_repo=PointHistoryRepo(db),
        tier_config_repo=TierConfigRepo(db),
        firestore_client=db,
    )


def _seed_user(db, uid: str) -> None:
    db.collection("users").document(uid).set(
        {
            "name": uid,
            "email": f"{uid}@test.com",
            "playTab": {
                "state": PlayTabStateEnum.MATCH_SCHEDULED.value,
                "activeMatchId": _MATCH_ID,
                "updatedAt": _NOW,
            },
        }
    )


def _seed_doubles_match(db) -> None:
    db.collection("matches").document(_MATCH_ID).set(
        {
            "sport": "tennis",
            "status": "scheduled",
            "matchType": "doubles",
            "scheduledAt": _NOW,
            "participants": [
                {
                    "uid": _A1,
                    "team": "A",
                    "role": "player",
                    "displayName": "A One",
                },
                {
                    "uid": _A2,
                    "team": "A",
                    "role": "player",
                    "displayName": "A Two",
                },
                {
                    "uid": _B1,
                    "team": "B",
                    "role": "player",
                    "displayName": "B One",
                },
                {
                    "uid": _B2,
                    "team": "B",
                    "role": "player",
                    "displayName": "B Two",
                },
            ],
            "participantUids": list(_ALL),
            "participantPair": None,
            "resultSubmittedBy": [],
            "score": None,
            "resultByUser": {},
        }
    )


def _seed_all(db) -> None:
    for uid in _ALL:
        _seed_user(db, uid)
    _seed_doubles_match(db)


def _state(db, uid: str) -> str:
    doc = db.collection("users").document(uid).get().to_dict() or {}
    return (doc.get("playTab") or {}).get("state", "")


def _match_status(db) -> str:
    doc = db.collection("matches").document(_MATCH_ID).get().to_dict() or {}
    return doc.get("status", "")


def _score() -> MatchScore:
    return MatchScore(
        sets=[SetScore(p1_games=6, p2_games=3), SetScore(p1_games=6, p2_games=4)]
    )


@pytest.fixture(autouse=True)
def _cleanup(db):
    yield
    for uid in _ALL:
        db.collection("users").document(uid).delete()
    db.collection("matches").document(_MATCH_ID).delete()


class TestFirstSubmission:
    def test_submitter_transitions_to_waiting_opponent(self, db):
        _seed_all(db)
        svc = _make_service(db)
        svc.verify_score(
            _A1, _MATCH_ID, VerifyScoreRequest(winner_team="A", score=_score())
        )
        assert _state(db, _A1) == PlayTabStateEnum.POST_MATCH_WAITING_OPPONENT.value

    def test_other_three_transition_to_confirm_required(self, db):
        _seed_all(db)
        svc = _make_service(db)
        svc.verify_score(
            _A1, _MATCH_ID, VerifyScoreRequest(winner_team="A", score=_score())
        )
        for uid in (_A2, _B1, _B2):
            assert _state(db, uid) == PlayTabStateEnum.POST_MATCH_CONFIRM_REQUIRED.value

    def test_match_status_becomes_pending_confirmation(self, db):
        _seed_all(db)
        svc = _make_service(db)
        svc.verify_score(
            _A1, _MATCH_ID, VerifyScoreRequest(winner_team="A", score=_score())
        )
        assert _match_status(db) == MatchStatusEnum.PENDING_CONFIRMATION

    def test_score_doc_persists_winner_team(self, db):
        _seed_all(db)
        svc = _make_service(db)
        svc.verify_score(
            _A1, _MATCH_ID, VerifyScoreRequest(winner_team="A", score=_score())
        )
        doc = db.collection("matches").document(_MATCH_ID).get().to_dict() or {}
        assert (doc.get("score") or {}).get("winnerTeam") == "A"

    def test_losing_side_player_can_submit(self, db):
        # The losing side (B) can also be the submitter — issue allows any
        # of the 4 to log the result.
        _seed_all(db)
        svc = _make_service(db)
        response = svc.verify_score(
            _B1, _MATCH_ID, VerifyScoreRequest(winner_team="A", score=_score())
        )
        assert response.status == MatchStatusEnum.PENDING_CONFIRMATION
        assert _state(db, _B1) == PlayTabStateEnum.POST_MATCH_WAITING_OPPONENT.value


class TestConfirmation:
    def test_opposing_team_completes_match(self, db):
        _seed_all(db)
        svc = _make_service(db)
        svc.verify_score(
            _A1, _MATCH_ID, VerifyScoreRequest(winner_team="A", score=_score())
        )
        # B1 (opposing team) confirms.
        response = svc.verify_score(_B1, _MATCH_ID, VerifyScoreRequest(winner_team="A"))
        assert response.status == MatchStatusEnum.COMPLETED
        assert _match_status(db) == MatchStatusEnum.COMPLETED
        for uid in _ALL:
            assert _state(db, uid) == PlayTabStateEnum.DISCOVERY.value

    def test_same_team_confirmation_rejected(self, db):
        _seed_all(db)
        svc = _make_service(db)
        svc.verify_score(
            _A1, _MATCH_ID, VerifyScoreRequest(winner_team="A", score=_score())
        )
        # A2 is on the same team as the original submitter A1.
        with pytest.raises(ValueError, match="opposing team"):
            svc.verify_score(_A2, _MATCH_ID, VerifyScoreRequest(winner_team="A"))
        # Match is still pending — same-team rejection must not change state.
        assert _match_status(db) == MatchStatusEnum.PENDING_CONFIRMATION

    def test_opposing_team_disagreement_disputes_match(self, db):
        _seed_all(db)
        svc = _make_service(db)
        svc.verify_score(
            _A1, _MATCH_ID, VerifyScoreRequest(winner_team="A", score=_score())
        )
        # B1 says the winner was actually B → dispute.
        response = svc.verify_score(_B1, _MATCH_ID, VerifyScoreRequest(winner_team="B"))
        assert response.status == MatchStatusEnum.DISPUTED
        assert _match_status(db) == MatchStatusEnum.DISPUTED
        for uid in _ALL:
            assert _state(db, uid) == PlayTabStateEnum.MATCH_DISPUTED.value
