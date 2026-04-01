"""
Unit tests for MatchConfirmationService.

All Firestore interactions are mocked. Tests cover:
- First submission (scheduled → pending_confirmation)
- Confirmation with scoring (pending_confirmation → completed)
- Dispute (pending_confirmation → disputed)
- Walkover (zero deltas, no pointHistory)
- Permission and state guards
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.models.common import MatchScore, SetScore
from app.models.enums import (
    MatchResultEnum,
    MatchStatusEnum,
    PointHistoryReasonEnum,
    SportEnum,
    TierEnum,
)
from app.models.match import Match, MatchParticipant, VerifyScoreRequest, ScoringPayload
from app.models.region_config import RegionConfig
from app.models.tier import TierConfig, TierThreshold
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.ticker_repo import TickerRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.match_confirmation_service import MatchConfirmationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WINNER_UID = "user_winner"
LOSER_UID = "user_loser"
MATCH_ID = "match_001"
SPORT = SportEnum.TENNIS


def _tier_config() -> TierConfig:
    return TierConfig(
        thresholds=[
            TierThreshold(
                tier=TierEnum.AMATEUR,
                min_pts=1000,
                max_pts=1999,
                label="Amateur",
                color="#aaa",
            ),
            TierThreshold(
                tier=TierEnum.INTERMEDIATE,
                min_pts=2000,
                max_pts=2999,
                label="Intermediate",
                color="#bbb",
            ),
            TierThreshold(
                tier=TierEnum.ADVANCED,
                min_pts=3000,
                max_pts=3999,
                label="Advanced",
                color="#ccc",
            ),
            TierThreshold(
                tier=TierEnum.COMPETITIVE,
                min_pts=4000,
                max_pts=None,
                label="Competitive",
                color="#ddd",
            ),
        ],
        version=1,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_match(
    status: MatchStatusEnum = MatchStatusEnum.SCHEDULED,
    score: MatchScore | None = None,
) -> Match:
    return Match(
        match_id=MATCH_ID,
        sport=SPORT,
        status=status,
        participant_uids=[WINNER_UID, LOSER_UID],
        participants=[
            MatchParticipant(uid=WINNER_UID, role="player"),
            MatchParticipant(uid=LOSER_UID, role="player"),
        ],
        score=score,
    )


def _make_score(winner_uid: str = WINNER_UID, retired: bool = False) -> MatchScore:
    return MatchScore(
        sets=[SetScore(p1_games=6, p2_games=3)], winner_uid=winner_uid, retired=retired
    )


def _region_config() -> RegionConfig:
    return RegionConfig(mapping={"101": "athens", "202": "thessaloniki"}, version=1)


def _make_service(
    match: Match | None = None,
    tier_config: TierConfig | None = None,
    with_ticker: bool = True,
) -> tuple[MatchConfirmationService, MagicMock, MagicMock, Mock, Mock]:
    """Build service with mocked repos and a mock Firestore client.

    Returns (service, mock_client, mock_ph_repo, mock_ticker_repo, mock_region_config_repo).
    """
    mock_matches_repo = Mock(spec=MatchesRepo)
    mock_matches_repo.get_by_id.return_value = match or _make_match()

    mock_users_repo = Mock(spec=UsersRepo)

    mock_ph_repo = Mock(spec=PointHistoryRepo)

    mock_tier_config_repo = Mock(spec=TierConfigRepo)
    mock_tier_config_repo.get.return_value = tier_config or _tier_config()

    mock_ticker_repo = Mock(spec=TickerRepo) if with_ticker else None
    mock_region_config_repo = Mock(spec=RegionConfigRepo) if with_ticker else None
    if mock_region_config_repo is not None:
        mock_region_config_repo.get.return_value = _region_config()

    mock_client = MagicMock()
    # Make client.transaction() return a fresh mock each call
    mock_txn = MagicMock()
    mock_client.transaction.return_value = mock_txn

    # Simulate @firestore.transactional: call the decorated fn with txn immediately
    def _call_transactional(fn):
        def wrapper(txn):
            return fn(txn)

        return wrapper

    service = MatchConfirmationService(
        mock_matches_repo,
        mock_users_repo,
        mock_ph_repo,
        mock_tier_config_repo,
        mock_client,
        ticker_repo=mock_ticker_repo,
        region_config_repo=mock_region_config_repo,
    )
    return service, mock_client, mock_ph_repo, mock_ticker_repo, mock_region_config_repo


def _make_user_snap(
    pts: int,
    tier: TierEnum,
    reg_tier: TierEnum | None = None,
    name: str = "Player",
    area: int = 101,
    current_streak: int = 0,
    best_streak: int = 0,
    personal_best: int | None = None,
) -> Mock:
    """Return a mock Firestore DocumentSnapshot with ranking data."""
    ranking: dict[str, object] = {
        "pts": pts,
        "tier": tier.value,
        "registrationTier": (reg_tier or tier).value,
        "currentStreak": current_streak,
        "bestStreak": best_streak,
    }
    if personal_best is not None:
        ranking["personalBest"] = personal_best
    snap = Mock()
    snap.to_dict.return_value = {
        "name": name,
        "preferences": {"area": area},
        "rankings": {SPORT.value: ranking},
    }
    return snap


# ---------------------------------------------------------------------------
# Tests: guards
# ---------------------------------------------------------------------------


class TestVerifyScoreGuards:
    def test_match_not_found_raises_value_error(self):
        service, _, _, _, _ = _make_service()
        service.matches_repo.get_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            service.verify_score(
                WINNER_UID, MATCH_ID, VerifyScoreRequest(winner_uid=WINNER_UID)
            )

    def test_non_participant_raises_permission_error(self):
        service, _, _, _, _ = _make_service()

        with pytest.raises(PermissionError):
            service.verify_score(
                "outsider_uid", MATCH_ID, VerifyScoreRequest(winner_uid=WINNER_UID)
            )

    def test_winner_uid_not_participant_raises_value_error(self):
        service, _, _, _, _ = _make_service()

        with pytest.raises(ValueError, match="not a participant"):
            service.verify_score(
                WINNER_UID, MATCH_ID, VerifyScoreRequest(winner_uid="unknown_uid")
            )

    def test_completed_match_raises_value_error(self):
        service, _, _, _, _ = _make_service(
            match=_make_match(status=MatchStatusEnum.COMPLETED)
        )

        with pytest.raises(ValueError, match="status"):
            service.verify_score(
                WINNER_UID, MATCH_ID, VerifyScoreRequest(winner_uid=WINNER_UID)
            )

    def test_disputed_match_raises_value_error(self):
        service, _, _, _, _ = _make_service(
            match=_make_match(status=MatchStatusEnum.DISPUTED)
        )

        with pytest.raises(ValueError, match="status"):
            service.verify_score(
                WINNER_UID, MATCH_ID, VerifyScoreRequest(winner_uid=WINNER_UID)
            )


# ---------------------------------------------------------------------------
# Tests: first submission (scheduled → pending_confirmation)
# ---------------------------------------------------------------------------


class TestFirstSubmission:
    def _run(self, *, score=None, walkover=False):
        service, mock_client, _, _, _ = _make_service()

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            # Make @firestore.transactional a pass-through decorator
            mock_fs.transactional = lambda fn: fn
            response = service.verify_score(
                WINNER_UID,
                MATCH_ID,
                VerifyScoreRequest(
                    winner_uid=WINNER_UID, score=score, walkover=walkover
                ),
            )
        return response, mock_client

    def test_returns_pending_confirmation_status(self):
        response, _ = self._run()
        assert response.status == MatchStatusEnum.PENDING_CONFIRMATION

    def test_returns_correct_winner_and_loser_uids(self):
        response, _ = self._run()
        assert response.winner_uid == WINNER_UID
        assert response.loser_uid == LOSER_UID

    def test_returns_zero_deltas(self):
        response, _ = self._run()
        assert response.winner_delta == 0
        assert response.loser_delta == 0
        assert response.winner_new_pts == 0
        assert response.loser_new_pts == 0

    def test_scoring_is_none(self):
        response, _ = self._run()
        assert response.scoring is None

    def test_writes_status_and_result_to_match(self):
        score = _make_score()
        response, mock_client = self._run(score=score)
        match_ref = mock_client.collection("matches").document(MATCH_ID)
        # update should have been called on the match ref
        match_ref.update.assert_not_called()  # txn.update is called, not direct update
        # The mock transaction's update is checked via the transaction mock
        txn = mock_client.transaction()
        assert txn.update.called


# ---------------------------------------------------------------------------
# Tests: second submission — confirmation (pending_confirmation → completed)
# ---------------------------------------------------------------------------


class TestConfirmationWithScoring:
    def _run_confirmation(self, winner_pts=2100, loser_pts=2050, **kwargs):
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _make_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION, score=stored_score
        )
        service, mock_client, mock_ph_repo, mock_ticker_repo, _ = _make_service(
            match=match,
        )

        winner_snap = _make_user_snap(winner_pts, TierEnum.INTERMEDIATE, name="Winner")
        loser_snap = _make_user_snap(loser_pts, TierEnum.INTERMEDIATE, name="Loser")

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            mock_fs.transactional = lambda fn: fn

            # MagicMock returns the same object regardless of arguments, so we use
            # side_effect to return distinct doc mocks per UID.
            winner_doc = MagicMock()
            loser_doc = MagicMock()
            winner_doc.get.return_value = winner_snap
            loser_doc.get.return_value = loser_snap

            _extra: dict[str, MagicMock] = {}

            def _get_doc(uid: str) -> MagicMock:
                if uid == WINNER_UID:
                    return winner_doc
                if uid == LOSER_UID:
                    return loser_doc
                return _extra.setdefault(uid, MagicMock())

            mock_client.collection.return_value.document.side_effect = _get_doc

            response = service.verify_score(
                LOSER_UID,
                MATCH_ID,
                VerifyScoreRequest(
                    winner_uid=WINNER_UID, score=_make_score(), **kwargs
                ),
            )
        return response, mock_client, mock_ph_repo, mock_ticker_repo

    def test_returns_completed_status(self):
        response, _, _, _ = self._run_confirmation()
        assert response.status == MatchStatusEnum.COMPLETED

    def test_winner_receives_positive_delta(self):
        response, _, _, _ = self._run_confirmation()
        assert response.winner_delta > 0

    def test_loser_delta_is_zero_for_same_tier(self):
        response, _, _, _ = self._run_confirmation()
        assert response.loser_delta == 0

    def test_winner_new_pts_is_pts_plus_delta(self):
        response, _, _, _ = self._run_confirmation(winner_pts=2100, loser_pts=2050)
        assert response.winner_new_pts == 2200  # base +100

    def test_point_history_entries_written_for_both_players(self):
        _, _, mock_ph_repo, _ = self._run_confirmation()
        assert mock_ph_repo.add_entry_in_transaction.call_count == 2

    def test_point_history_winner_entry_has_match_win_reason(self):
        _, _, mock_ph_repo, _ = self._run_confirmation()
        calls = mock_ph_repo.add_entry_in_transaction.call_args_list
        winner_call = next(c for c in calls if c.args[1] == WINNER_UID)
        winner_entry = winner_call.args[2]
        assert winner_entry.reason == PointHistoryReasonEnum.MATCH_WIN

    def test_point_history_loser_entry_has_match_loss_reason(self):
        _, _, mock_ph_repo, _ = self._run_confirmation()
        calls = mock_ph_repo.add_entry_in_transaction.call_args_list
        loser_call = next(c for c in calls if c.args[1] == LOSER_UID)
        loser_entry = loser_call.args[2]
        assert loser_entry.reason == PointHistoryReasonEnum.MATCH_LOSS

    def test_match_updates_include_finished_at_and_result_by_user(self):
        _, mock_client, _, _ = self._run_confirmation()
        txn = mock_client.transaction()
        match_ref = mock_client.collection("matches").document(MATCH_ID)
        update_calls = [c for c in txn.update.call_args_list if c.args[0] == match_ref]
        assert update_calls, "match should have been updated in transaction"
        update_data = update_calls[0].args[1]
        assert update_data["status"] == MatchStatusEnum.COMPLETED
        assert "finishedAt" in update_data
        assert update_data["resultByUser"][WINNER_UID] == MatchResultEnum.WIN
        assert update_data["resultByUser"][LOSER_UID] == MatchResultEnum.LOSS

    def test_scoring_payload_present_on_completion(self):
        response, _, _, _ = self._run_confirmation()
        assert response.scoring is not None
        assert isinstance(response.scoring, ScoringPayload)

    def test_scoring_payload_loser_perspective_same_tier(self):
        # Caller is LOSER_UID (same tier as winner) — no penalty, delta 0
        response, _, _, _ = self._run_confirmation(winner_pts=2100, loser_pts=2050)
        s = response.scoring
        assert s is not None
        assert s.sport == SPORT
        assert s.your_pts_before == 2050
        assert s.your_pts_after == 2050  # no penalty for same tier
        assert s.delta == 0
        assert s.breakdown.base_win == 0
        assert s.breakdown.upset_bonus == 0
        assert s.breakdown.elo_bonus == 0
        assert s.breakdown.penalty == 0
        assert s.tier_before == TierEnum.INTERMEDIATE
        assert s.tier_after == TierEnum.INTERMEDIATE
        assert s.tier_crossed is False

    def test_scoring_payload_winner_perspective(self):
        # Re-run with WINNER_UID as caller (same tier match)
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _make_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION, score=stored_score
        )
        service, mock_client, _, _, _ = _make_service(match=match)

        winner_snap = _make_user_snap(2100, TierEnum.INTERMEDIATE, name="Winner")
        loser_snap = _make_user_snap(2050, TierEnum.INTERMEDIATE, name="Loser")

        winner_doc = MagicMock()
        loser_doc = MagicMock()
        winner_doc.get.return_value = winner_snap
        loser_doc.get.return_value = loser_snap
        _extra: dict[str, MagicMock] = {}

        def _get_doc(uid: str) -> MagicMock:
            if uid == WINNER_UID:
                return winner_doc
            if uid == LOSER_UID:
                return loser_doc
            return _extra.setdefault(uid, MagicMock())

        mock_client.collection.return_value.document.side_effect = _get_doc

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            mock_fs.transactional = lambda fn: fn
            response = service.verify_score(
                WINNER_UID,
                MATCH_ID,
                VerifyScoreRequest(winner_uid=WINNER_UID, score=_make_score()),
            )

        s = response.scoring
        assert s is not None
        assert s.your_pts_before == 2100
        assert s.your_pts_after == 2200  # base +100
        assert s.delta == 100
        assert s.breakdown.base_win == 100
        assert s.breakdown.upset_bonus == 0
        assert s.breakdown.elo_bonus == 0
        assert s.breakdown.penalty == 0
        assert s.tier_crossed is False


# ---------------------------------------------------------------------------
# Tests: dispute
# ---------------------------------------------------------------------------


class TestDispute:
    def test_dispute_when_winner_uid_differs(self):
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _make_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION, score=stored_score
        )
        service, mock_client, mock_ph_repo, _, _ = _make_service(match=match)

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            mock_fs.transactional = lambda fn: fn

            # Loser disputes: claims they won
            response = service.verify_score(
                LOSER_UID,
                MATCH_ID,
                VerifyScoreRequest(winner_uid=LOSER_UID),
            )

        assert response.status == MatchStatusEnum.DISPUTED
        assert response.winner_delta == 0
        assert response.scoring is None
        # No pointHistory written
        mock_ph_repo.add_entry_in_transaction.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: walkover
# ---------------------------------------------------------------------------


class TestWalkover:
    def _run_walkover(self):
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _make_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION, score=stored_score
        )
        service, mock_client, mock_ph_repo, mock_ticker_repo, _ = _make_service(
            match=match,
        )

        winner_snap = _make_user_snap(2100, TierEnum.INTERMEDIATE)
        loser_snap = _make_user_snap(2050, TierEnum.INTERMEDIATE)

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            mock_fs.transactional = lambda fn: fn

            winner_doc = MagicMock()
            loser_doc = MagicMock()
            winner_doc.get.return_value = winner_snap
            loser_doc.get.return_value = loser_snap

            _extra: dict[str, MagicMock] = {}

            def _get_doc(uid: str) -> MagicMock:
                if uid == WINNER_UID:
                    return winner_doc
                if uid == LOSER_UID:
                    return loser_doc
                return _extra.setdefault(uid, MagicMock())

            mock_client.collection.return_value.document.side_effect = _get_doc

            response = service.verify_score(
                LOSER_UID,
                MATCH_ID,
                VerifyScoreRequest(winner_uid=WINNER_UID, walkover=True),
            )
        return response, mock_ph_repo, mock_ticker_repo

    def test_walkover_completes_match(self):
        response, _, _ = self._run_walkover()
        assert response.status == MatchStatusEnum.COMPLETED

    def test_walkover_produces_zero_deltas(self):
        response, _, _ = self._run_walkover()
        assert response.winner_delta == 0
        assert response.loser_delta == 0

    def test_walkover_does_not_write_point_history(self):
        _, mock_ph_repo, _ = self._run_walkover()
        mock_ph_repo.add_entry_in_transaction.assert_not_called()

    def test_walkover_does_not_write_ticker(self):
        _, _, mock_ticker_repo = self._run_walkover()
        mock_ticker_repo.add.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: upset ticker events
# ---------------------------------------------------------------------------


class TestUpsetTickerEvent:
    """Tests for upset event detection and ticker write during match confirmation."""

    def _run_upset_confirmation(
        self,
        winner_tier: TierEnum = TierEnum.AMATEUR,
        loser_tier: TierEnum = TierEnum.INTERMEDIATE,
        winner_pts: int = 1500,
        loser_pts: int = 2100,
        winner_name: str = "Underdog",
        winner_area: int = 101,
    ):
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _make_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION, score=stored_score
        )
        service, mock_client, _, mock_ticker_repo, mock_region_repo = _make_service(
            match=match,
        )

        winner_snap = _make_user_snap(
            winner_pts, winner_tier, name=winner_name, area=winner_area
        )
        loser_snap = _make_user_snap(loser_pts, loser_tier, name="Favourite")

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            mock_fs.transactional = lambda fn: fn

            winner_doc = MagicMock()
            loser_doc = MagicMock()
            winner_doc.get.return_value = winner_snap
            loser_doc.get.return_value = loser_snap

            _extra: dict[str, MagicMock] = {}

            def _get_doc(uid: str) -> MagicMock:
                if uid == WINNER_UID:
                    return winner_doc
                if uid == LOSER_UID:
                    return loser_doc
                return _extra.setdefault(uid, MagicMock())

            mock_client.collection.return_value.document.side_effect = _get_doc

            response = service.verify_score(
                LOSER_UID,
                MATCH_ID,
                VerifyScoreRequest(winner_uid=WINNER_UID, score=_make_score()),
            )
        return response, mock_ticker_repo, mock_region_repo

    def test_upset_writes_ticker_event(self):
        _, mock_ticker_repo, _ = self._run_upset_confirmation(
            winner_tier=TierEnum.AMATEUR, loser_tier=TierEnum.INTERMEDIATE
        )
        assert mock_ticker_repo is not None
        mock_ticker_repo.add.assert_called_once()
        event = mock_ticker_repo.add.call_args.args[0]
        assert event.type.value == "upset"
        assert event.winner_uid == WINNER_UID
        assert event.winner_name == "Underdog"
        assert event.loser_tier == TierEnum.INTERMEDIATE
        assert event.sport == SPORT
        assert event.region == "athens"
        assert event.delta > 0

    def test_upset_ticker_has_24h_ttl(self):
        _, mock_ticker_repo, _ = self._run_upset_confirmation()
        assert mock_ticker_repo is not None
        event = mock_ticker_repo.add.call_args.args[0]
        ttl = event.expires_at - event.created_at
        assert ttl.total_seconds() == 24 * 3600

    def test_no_ticker_when_same_tier(self):
        _, mock_ticker_repo, _ = self._run_upset_confirmation(
            winner_tier=TierEnum.INTERMEDIATE, loser_tier=TierEnum.INTERMEDIATE
        )
        assert mock_ticker_repo is not None
        mock_ticker_repo.add.assert_not_called()

    def test_no_ticker_when_winner_higher_tier(self):
        _, mock_ticker_repo, _ = self._run_upset_confirmation(
            winner_tier=TierEnum.ADVANCED, loser_tier=TierEnum.INTERMEDIATE
        )
        assert mock_ticker_repo is not None
        mock_ticker_repo.add.assert_not_called()

    def test_ticker_failure_does_not_break_match_confirmation(self):
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _make_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION, score=stored_score
        )
        service, mock_client, _, mock_ticker_repo, _ = _make_service(match=match)
        assert mock_ticker_repo is not None
        mock_ticker_repo.add.side_effect = Exception("Firestore timeout")

        winner_snap = _make_user_snap(1500, TierEnum.AMATEUR, name="Underdog", area=101)
        loser_snap = _make_user_snap(2100, TierEnum.INTERMEDIATE, name="Favourite")

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            mock_fs.transactional = lambda fn: fn

            winner_doc = MagicMock()
            loser_doc = MagicMock()
            winner_doc.get.return_value = winner_snap
            loser_doc.get.return_value = loser_snap

            _extra: dict[str, MagicMock] = {}

            def _get_doc(uid: str) -> MagicMock:
                if uid == WINNER_UID:
                    return winner_doc
                if uid == LOSER_UID:
                    return loser_doc
                return _extra.setdefault(uid, MagicMock())

            mock_client.collection.return_value.document.side_effect = _get_doc

            response = service.verify_score(
                LOSER_UID,
                MATCH_ID,
                VerifyScoreRequest(winner_uid=WINNER_UID, score=_make_score()),
            )

        # Match still completes despite ticker failure
        assert response.status == MatchStatusEnum.COMPLETED
        assert response.winner_delta > 0

    def test_no_ticker_when_repos_not_configured(self):
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _make_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION, score=stored_score
        )
        service, mock_client, _, mock_ticker_repo, _ = _make_service(
            match=match, with_ticker=False
        )

        winner_snap = _make_user_snap(1500, TierEnum.AMATEUR, name="Underdog", area=101)
        loser_snap = _make_user_snap(2100, TierEnum.INTERMEDIATE, name="Favourite")

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            mock_fs.transactional = lambda fn: fn

            winner_doc = MagicMock()
            loser_doc = MagicMock()
            winner_doc.get.return_value = winner_snap
            loser_doc.get.return_value = loser_snap

            _extra: dict[str, MagicMock] = {}

            def _get_doc(uid: str) -> MagicMock:
                if uid == WINNER_UID:
                    return winner_doc
                if uid == LOSER_UID:
                    return loser_doc
                return _extra.setdefault(uid, MagicMock())

            mock_client.collection.return_value.document.side_effect = _get_doc

            response = service.verify_score(
                LOSER_UID,
                MATCH_ID,
                VerifyScoreRequest(winner_uid=WINNER_UID, score=_make_score()),
            )

        # Match still completes without ticker repos
        assert response.status == MatchStatusEnum.COMPLETED
        assert mock_ticker_repo is None


class TestRetirementFromStoredScore:
    """When the first submitter stored retired=True on the match and the confirmer
    does not resend score, is_walkover must still be True so pointHistory and
    ticker writes are skipped."""

    def _run_stored_retirement(
        self,
        winner_current_streak: int = 3,
        winner_best_streak: int = 5,
        winner_personal_best: int | None = 1800,
    ):
        stored_score = _make_score(retired=True)
        match = _make_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION, score=stored_score
        )
        service, mock_client, mock_ph_repo, mock_ticker_repo, _ = _make_service(
            match=match,
        )

        winner_snap = _make_user_snap(
            1500,
            TierEnum.AMATEUR,
            current_streak=winner_current_streak,
            best_streak=winner_best_streak,
            personal_best=winner_personal_best,
        )
        loser_snap = _make_user_snap(2100, TierEnum.INTERMEDIATE)

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            mock_fs.transactional = lambda fn: fn

            winner_doc = MagicMock()
            loser_doc = MagicMock()
            winner_doc.get.return_value = winner_snap
            loser_doc.get.return_value = loser_snap

            _extra: dict[str, MagicMock] = {}

            def _get_doc(uid: str) -> MagicMock:
                if uid == WINNER_UID:
                    return winner_doc
                if uid == LOSER_UID:
                    return loser_doc
                return _extra.setdefault(uid, MagicMock())

            mock_client.collection.return_value.document.side_effect = _get_doc

            # Confirmer agrees with winner but does NOT resend score
            response = service.verify_score(
                LOSER_UID,
                MATCH_ID,
                VerifyScoreRequest(winner_uid=WINNER_UID),
            )
        return response, mock_ph_repo, mock_ticker_repo, mock_client

    def _get_user_update(self, mock_client: MagicMock, uid: str) -> dict[str, Any]:
        """Extract the update dict written to a user doc in the transaction."""
        txn = mock_client.transaction()
        user_ref = mock_client.collection("users").document(uid)
        update_calls = [c for c in txn.update.call_args_list if c.args[0] == user_ref]
        assert update_calls, f"expected update call for {uid}"
        return update_calls[0].args[1]

    def test_stored_retirement_does_not_write_point_history(self):
        _, mock_ph_repo, _, _ = self._run_stored_retirement()
        mock_ph_repo.add_entry_in_transaction.assert_not_called()

    def test_stored_retirement_does_not_write_ticker(self):
        _, _, mock_ticker_repo, _ = self._run_stored_retirement()
        mock_ticker_repo.add.assert_not_called()

    def test_stored_retirement_produces_zero_deltas(self):
        response, _, _, _ = self._run_stored_retirement()
        assert response.winner_delta == 0
        assert response.loser_delta == 0

    def test_retirement_preserves_winner_streak(self):
        _, _, _, mock_client = self._run_stored_retirement(
            winner_current_streak=3, winner_best_streak=5
        )
        updates = self._get_user_update(mock_client, WINNER_UID)
        assert updates[f"rankings.{SPORT.value}.currentStreak"] == 3
        assert updates[f"rankings.{SPORT.value}.bestStreak"] == 5

    def test_retirement_preserves_winner_personal_best(self):
        _, _, _, mock_client = self._run_stored_retirement(winner_personal_best=1800)
        updates = self._get_user_update(mock_client, WINNER_UID)
        pb_key = f"rankings.{SPORT.value}.personalBest"
        assert pb_key not in updates or updates[pb_key] == 1800


# ---------------------------------------------------------------------------
# Tests: streak + personal best updates (CH-5)
# ---------------------------------------------------------------------------


class TestStreakAndPersonalBest:
    """Tests that match confirmation updates streak + personalBest fields."""

    def _run_confirmation_with_streaks(
        self,
        winner_pts: int = 2100,
        loser_pts: int = 2050,
        winner_current_streak: int = 0,
        winner_best_streak: int = 0,
        winner_personal_best: int | None = None,
        loser_current_streak: int = 3,
        loser_best_streak: int = 5,
        walkover: bool = False,
    ):
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _make_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION, score=stored_score
        )
        service, mock_client, _, _, _ = _make_service(match=match)

        winner_snap = _make_user_snap(
            winner_pts,
            TierEnum.INTERMEDIATE,
            name="Winner",
            current_streak=winner_current_streak,
            best_streak=winner_best_streak,
            personal_best=winner_personal_best,
        )
        loser_snap = _make_user_snap(
            loser_pts,
            TierEnum.INTERMEDIATE,
            name="Loser",
            current_streak=loser_current_streak,
            best_streak=loser_best_streak,
        )

        with patch("app.services.match_confirmation_service.firestore") as mock_fs:
            mock_fs.transactional = lambda fn: fn

            winner_doc = MagicMock()
            loser_doc = MagicMock()
            winner_doc.get.return_value = winner_snap
            loser_doc.get.return_value = loser_snap

            _extra: dict[str, MagicMock] = {}

            def _get_doc(uid: str) -> MagicMock:
                if uid == WINNER_UID:
                    return winner_doc
                if uid == LOSER_UID:
                    return loser_doc
                return _extra.setdefault(uid, MagicMock())

            mock_client.collection.return_value.document.side_effect = _get_doc

            response = service.verify_score(
                LOSER_UID,
                MATCH_ID,
                VerifyScoreRequest(
                    winner_uid=WINNER_UID, score=_make_score(), walkover=walkover
                ),
            )
        return response, mock_client

    def _get_user_update(self, mock_client: MagicMock, uid: str) -> dict[str, Any]:
        """Extract the update dict written to a user doc in the transaction."""
        txn = mock_client.transaction()
        user_ref = mock_client.collection("users").document(uid)
        update_calls = [c for c in txn.update.call_args_list if c.args[0] == user_ref]
        assert update_calls, f"expected update call for {uid}"
        return update_calls[0].args[1]

    # --- Winner streak ---

    def test_winner_streak_increments_by_one(self):
        _, mock_client = self._run_confirmation_with_streaks(
            winner_current_streak=2, winner_best_streak=5
        )
        updates = self._get_user_update(mock_client, WINNER_UID)
        assert updates[f"rankings.{SPORT.value}.currentStreak"] == 3

    def test_winner_best_streak_updates_when_exceeded(self):
        _, mock_client = self._run_confirmation_with_streaks(
            winner_current_streak=5, winner_best_streak=5
        )
        updates = self._get_user_update(mock_client, WINNER_UID)
        # currentStreak becomes 6, which exceeds bestStreak of 5
        assert updates[f"rankings.{SPORT.value}.currentStreak"] == 6
        assert updates[f"rankings.{SPORT.value}.bestStreak"] == 6

    def test_winner_best_streak_unchanged_when_not_exceeded(self):
        _, mock_client = self._run_confirmation_with_streaks(
            winner_current_streak=1, winner_best_streak=10
        )
        updates = self._get_user_update(mock_client, WINNER_UID)
        assert updates[f"rankings.{SPORT.value}.currentStreak"] == 2
        assert updates[f"rankings.{SPORT.value}.bestStreak"] == 10

    # --- Winner personal best ---

    def test_winner_personal_best_set_when_none(self):
        # Winner gets 2200 pts (base +100), no previous PB
        _, mock_client = self._run_confirmation_with_streaks(
            winner_pts=2100, winner_personal_best=None
        )
        updates = self._get_user_update(mock_client, WINNER_UID)
        assert updates[f"rankings.{SPORT.value}.personalBest"] == 2200

    def test_winner_personal_best_updates_when_exceeded(self):
        _, mock_client = self._run_confirmation_with_streaks(
            winner_pts=2100, winner_personal_best=2150
        )
        updates = self._get_user_update(mock_client, WINNER_UID)
        # New pts = 2200, exceeds PB of 2150
        assert updates[f"rankings.{SPORT.value}.personalBest"] == 2200

    def test_winner_personal_best_unchanged_when_not_exceeded(self):
        _, mock_client = self._run_confirmation_with_streaks(
            winner_pts=2100, winner_personal_best=2500
        )
        updates = self._get_user_update(mock_client, WINNER_UID)
        # New pts = 2200, does NOT exceed PB of 2500
        assert f"rankings.{SPORT.value}.personalBest" not in updates or (
            updates.get(f"rankings.{SPORT.value}.personalBest") == 2500
        )

    # --- Loser streak ---

    def test_loser_streak_resets_to_zero(self):
        _, mock_client = self._run_confirmation_with_streaks(
            loser_current_streak=3, loser_best_streak=5
        )
        updates = self._get_user_update(mock_client, LOSER_UID)
        assert updates[f"rankings.{SPORT.value}.currentStreak"] == 0

    def test_loser_best_streak_unchanged(self):
        _, mock_client = self._run_confirmation_with_streaks(
            loser_current_streak=3, loser_best_streak=5
        )
        updates = self._get_user_update(mock_client, LOSER_UID)
        assert updates[f"rankings.{SPORT.value}.bestStreak"] == 5

    # --- Loser personal best should never be written ---

    def test_loser_personal_best_not_in_update(self):
        _, mock_client = self._run_confirmation_with_streaks(
            winner_pts=2100, loser_pts=2050
        )
        updates = self._get_user_update(mock_client, LOSER_UID)
        assert f"rankings.{SPORT.value}.personalBest" not in updates

    # --- Walkover: no streak/PB changes ---

    def test_walkover_does_not_change_winner_streak(self):
        _, mock_client = self._run_confirmation_with_streaks(
            winner_current_streak=2, winner_best_streak=5, walkover=True
        )
        updates = self._get_user_update(mock_client, WINNER_UID)
        assert updates[f"rankings.{SPORT.value}.currentStreak"] == 2
        assert updates[f"rankings.{SPORT.value}.bestStreak"] == 5

    def test_walkover_does_not_change_loser_streak(self):
        _, mock_client = self._run_confirmation_with_streaks(
            loser_current_streak=3, loser_best_streak=5, walkover=True
        )
        updates = self._get_user_update(mock_client, LOSER_UID)
        assert updates[f"rankings.{SPORT.value}.currentStreak"] == 3
        assert updates[f"rankings.{SPORT.value}.bestStreak"] == 5

    def test_walkover_does_not_change_winner_personal_best(self):
        _, mock_client = self._run_confirmation_with_streaks(
            winner_pts=2100, winner_personal_best=2500, walkover=True
        )
        updates = self._get_user_update(mock_client, WINNER_UID)
        pb_key = f"rankings.{SPORT.value}.personalBest"
        assert pb_key not in updates or updates[pb_key] == 2500
