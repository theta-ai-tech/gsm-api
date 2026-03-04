"""
MatchConfirmationService — extends match confirmation with inline scoring.

Transaction flow for POST /matches/{matchId}/verify-score:

  First submission (match is 'scheduled'):
    Writes: match → pending_confirmation + stores score/winner

  Second submission — confirmation (match is 'pending_confirmation', winner agrees):
    Reads:  match, users/{winnerUid}, users/{loserUid}   (inside txn)
    Writes: match → completed + finishedAt + resultByUser + score
            users/{winnerUid}.rankings.{sport} → updated pts/tier
            users/{loserUid}.rankings.{sport}  → updated pts/tier
            users/{winnerUid}/pointHistory/{auto}
            users/{loserUid}/pointHistory/{auto}
            users/{winnerUid}.playTab → DISCOVERY
            users/{loserUid}.playTab  → DISCOVERY

  Second submission — dispute (winner disagrees):
    Writes: match → disputed
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.common import MatchScore
from app.models.enums import MatchResultEnum, MatchStatusEnum, PointHistoryReasonEnum, TierEnum
from app.models.match import Match, VerifyScoreRequest, VerifyScoreResponse
from app.models.point_history import PointHistoryEntry
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.scoring_service import ScoringResult, compute_match_scoring

_DEFAULT_PTS = 1000
_DEFAULT_TIER = TierEnum.AMATEUR


def _score_to_doc(score: MatchScore, winner_uid: str) -> dict[str, Any]:
    return {
        "sets": [
            {
                "p1Games": s.p1_games,
                "p2Games": s.p2_games,
                "tiebreakScore": s.tiebreak_score,
            }
            for s in score.sets
        ],
        "winnerUid": winner_uid,
        "retired": score.retired,
    }


def _ranking_field(sport_value: str, field: str) -> str:
    return f"rankings.{sport_value}.{field}"


class MatchConfirmationService:
    def __init__(
        self,
        matches_repo: MatchesRepo,
        users_repo: UsersRepo,
        point_history_repo: PointHistoryRepo,
        tier_config_repo: TierConfigRepo,
        firestore_client: firestore.Client,
    ):
        self.matches_repo = matches_repo
        self.users_repo = users_repo
        self.point_history_repo = point_history_repo
        self.tier_config_repo = tier_config_repo
        self.client = firestore_client

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def verify_score(
        self,
        uid: str,
        match_id: str,
        request: VerifyScoreRequest,
    ) -> VerifyScoreResponse:
        """Submit or confirm a match result, running inline scoring on confirmation."""
        match = self.matches_repo.get_by_id(match_id)
        if match is None:
            raise ValueError(f"Match {match_id} not found")

        if uid not in match.participant_uids:
            raise PermissionError("You are not a participant in this match")

        if match.status not in (MatchStatusEnum.SCHEDULED, MatchStatusEnum.PENDING_CONFIRMATION):
            raise ValueError(f"Cannot submit result for a match with status '{match.status}'")

        if request.winner_uid not in match.participant_uids:
            raise ValueError("winner_uid is not a participant in this match")

        now = datetime.now(timezone.utc)

        if match.status == MatchStatusEnum.SCHEDULED:
            return self._first_submission(uid, match_id, match, request, now)
        else:
            return self._second_submission(uid, match_id, match, request, now)

    # -------------------------------------------------------------------------
    # First submission: scheduled → pending_confirmation
    # -------------------------------------------------------------------------

    def _first_submission(
        self,
        uid: str,
        match_id: str,
        match: Match,
        request: VerifyScoreRequest,
        now: datetime,
    ) -> VerifyScoreResponse:
        winner_uid = request.winner_uid
        loser_uid = next(p for p in match.participant_uids if p != winner_uid)
        caller_result = MatchResultEnum.WIN if uid == winner_uid else MatchResultEnum.LOSS

        match_ref = self.client.collection("matches").document(match_id)
        score_doc = _score_to_doc(request.score, winner_uid) if request.score else None

        transaction = self.client.transaction()

        @firestore.transactional
        def _txn(txn: firestore.Transaction) -> None:
            updates: dict[str, Any] = {
                "status": MatchStatusEnum.PENDING_CONFIRMATION,
                f"resultByUser.{uid}": caller_result,
            }
            if score_doc is not None:
                updates["score"] = score_doc
            txn.update(match_ref, updates)

        _txn(transaction)

        return VerifyScoreResponse(
            match_id=match_id,
            status=MatchStatusEnum.PENDING_CONFIRMATION,
            winner_uid=winner_uid,
            loser_uid=loser_uid,
            winner_delta=0,
            loser_delta=0,
            winner_new_pts=0,
            loser_new_pts=0,
        )

    # -------------------------------------------------------------------------
    # Second submission: pending_confirmation → completed or disputed
    # -------------------------------------------------------------------------

    def _second_submission(
        self,
        uid: str,
        match_id: str,
        match: Match,
        request: VerifyScoreRequest,
        now: datetime,
    ) -> VerifyScoreResponse:
        winner_uid = request.winner_uid
        loser_uid = next(p for p in match.participant_uids if p != winner_uid)

        stored_winner_uid = match.score.winner_uid if match.score else None

        if stored_winner_uid is not None and stored_winner_uid != winner_uid:
            return self._dispute(uid, match_id, winner_uid, loser_uid, request)

        return self._complete_with_scoring(
            uid, match_id, match, request, winner_uid, loser_uid, now
        )

    def _dispute(
        self,
        uid: str,
        match_id: str,
        winner_uid: str,
        loser_uid: str,
        request: VerifyScoreRequest,
    ) -> VerifyScoreResponse:
        caller_result = MatchResultEnum.WIN if uid == winner_uid else MatchResultEnum.LOSS
        match_ref = self.client.collection("matches").document(match_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def _txn(txn: firestore.Transaction) -> None:
            txn.update(
                match_ref,
                {
                    "status": MatchStatusEnum.DISPUTED,
                    f"resultByUser.{uid}": caller_result,
                },
            )

        _txn(transaction)

        return VerifyScoreResponse(
            match_id=match_id,
            status=MatchStatusEnum.DISPUTED,
            winner_uid=winner_uid,
            loser_uid=loser_uid,
            winner_delta=0,
            loser_delta=0,
            winner_new_pts=0,
            loser_new_pts=0,
        )

    # -------------------------------------------------------------------------
    # Completion with inline scoring
    # -------------------------------------------------------------------------

    def _complete_with_scoring(
        self,
        uid: str,
        match_id: str,
        match: Match,
        request: VerifyScoreRequest,
        winner_uid: str,
        loser_uid: str,
        now: datetime,
    ) -> VerifyScoreResponse:
        tier_config = self.tier_config_repo.get()
        sport = match.sport
        sport_value = sport.value
        is_walkover = request.walkover or (request.score is not None and request.score.retired)

        match_ref = self.client.collection("matches").document(match_id)
        winner_ref = self.client.collection("users").document(winner_uid)
        loser_ref = self.client.collection("users").document(loser_uid)
        ph_repo = self.point_history_repo

        # Effective score: prefer request.score, fall back to stored score
        effective_score = request.score or match.score

        result_holder: dict[str, ScoringResult] = {}

        @firestore.transactional
        def _scoring_txn(txn: firestore.Transaction) -> None:
            # --- READS (must precede all writes) ---
            winner_snap = winner_ref.get(transaction=txn)
            loser_snap = loser_ref.get(transaction=txn)

            winner_data = winner_snap.to_dict() or {}
            loser_data = loser_snap.to_dict() or {}

            winner_ranking = (winner_data.get("rankings") or {}).get(sport_value) or {}
            loser_ranking = (loser_data.get("rankings") or {}).get(sport_value) or {}

            winner_pts = int(winner_ranking.get("pts", _DEFAULT_PTS))
            loser_pts = int(loser_ranking.get("pts", _DEFAULT_PTS))
            winner_tier = TierEnum(winner_ranking.get("tier", _DEFAULT_TIER))
            loser_tier = TierEnum(loser_ranking.get("tier", _DEFAULT_TIER))
            winner_reg_tier = TierEnum(winner_ranking.get("registrationTier", winner_tier))
            loser_reg_tier = TierEnum(loser_ranking.get("registrationTier", loser_tier))

            # --- COMPUTE (pure, no IO) ---
            scoring = compute_match_scoring(
                winner_pts=winner_pts,
                loser_pts=loser_pts,
                winner_tier=winner_tier,
                loser_tier=loser_tier,
                winner_reg_tier=winner_reg_tier,
                loser_reg_tier=loser_reg_tier,
                tier_config=tier_config,
                walkover=is_walkover,
                retired=effective_score.retired if effective_score else False,
            )
            result_holder["scoring"] = scoring

            score_doc = _score_to_doc(effective_score, winner_uid) if effective_score else None

            # --- WRITES ---
            # 1. Match
            txn.update(
                match_ref,
                {
                    "status": MatchStatusEnum.COMPLETED,
                    "finishedAt": now,
                    "resultByUser": {
                        winner_uid: MatchResultEnum.WIN,
                        loser_uid: MatchResultEnum.LOSS,
                    },
                    "score": score_doc,
                },
            )

            # 2. Winner ranking + playTab
            txn.update(
                winner_ref,
                {
                    _ranking_field(sport_value, "pts"): scoring.winner_new_pts,
                    _ranking_field(sport_value, "tier"): scoring.winner_new_tier.value,
                    _ranking_field(sport_value, "lastUpdated"): now,
                    "playTab.state": "DISCOVERY",
                    "playTab.activeMatchId": None,
                    "playTab.updatedAt": now,
                },
            )

            # 3. Loser ranking + playTab
            txn.update(
                loser_ref,
                {
                    _ranking_field(sport_value, "pts"): scoring.loser_new_pts,
                    _ranking_field(sport_value, "tier"): scoring.loser_new_tier.value,
                    _ranking_field(sport_value, "lastUpdated"): now,
                    "playTab.state": "DISCOVERY",
                    "playTab.activeMatchId": None,
                    "playTab.updatedAt": now,
                },
            )

            # 4. pointHistory — skipped for walkover/retirement (zero deltas, no audit trail)
            if not is_walkover:
                winner_entry = PointHistoryEntry(
                    entry_id="",
                    sport=sport,
                    pts=scoring.winner_new_pts,
                    delta=scoring.winner_delta.total,
                    reason=PointHistoryReasonEnum.MATCH_WIN,
                    match_id=match_id,
                    opponent_uid=loser_uid,
                    opponent_pts_before=loser_pts,
                    league_id=match.league_id,
                    created_at=now,
                    tier_before=winner_tier,
                    tier_after=scoring.winner_new_tier,
                )
                loser_entry = PointHistoryEntry(
                    entry_id="",
                    sport=sport,
                    pts=scoring.loser_new_pts,
                    delta=scoring.loser_delta.total,
                    reason=PointHistoryReasonEnum.MATCH_LOSS,
                    match_id=match_id,
                    opponent_uid=winner_uid,
                    opponent_pts_before=winner_pts,
                    league_id=match.league_id,
                    created_at=now,
                    tier_before=loser_tier,
                    tier_after=scoring.loser_new_tier,
                )
                ph_repo.add_entry_in_transaction(txn, winner_uid, winner_entry)
                ph_repo.add_entry_in_transaction(txn, loser_uid, loser_entry)

        _scoring_txn(self.client.transaction())

        scoring = result_holder["scoring"]
        return VerifyScoreResponse(
            match_id=match_id,
            status=MatchStatusEnum.COMPLETED,
            winner_uid=winner_uid,
            loser_uid=loser_uid,
            winner_delta=scoring.winner_delta.total,
            loser_delta=scoring.loser_delta.total,
            winner_new_pts=scoring.winner_new_pts,
            loser_new_pts=scoring.loser_new_pts,
        )
