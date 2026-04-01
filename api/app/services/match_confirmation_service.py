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

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.common import MatchScore
from app.models.enums import (
    MatchResultEnum,
    MatchStatusEnum,
    PointHistoryReasonEnum,
    TierEnum,
    TickerEventTypeEnum,
)
from app.models.match import (
    Match,
    ScoringBreakdown,
    ScoringPayload,
    VerifyScoreRequest,
    VerifyScoreResponse,
)
from app.models.point_history import PointHistoryEntry
from app.models.ticker import TickerEvent
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.ticker_repo import TickerRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.clubhouse_service import (
    check_personal_best,
    update_streak_on_loss,
    update_streak_on_win,
)
from app.services.scoring_service import TIER_ORDER, compute_match_scoring

logger = logging.getLogger(__name__)

_DEFAULT_PTS = 1000
_DEFAULT_TIER = TierEnum.AMATEUR
_TICKER_TTL_HOURS = 24


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
        ticker_repo: TickerRepo | None = None,
        region_config_repo: RegionConfigRepo | None = None,
    ):
        self.matches_repo = matches_repo
        self.users_repo = users_repo
        self.point_history_repo = point_history_repo
        self.tier_config_repo = tier_config_repo
        self.client = firestore_client
        self.ticker_repo = ticker_repo
        self.region_config_repo = region_config_repo

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
        match_ref = self.client.collection("matches").document(match_id)
        winner_ref = self.client.collection("users").document(winner_uid)
        loser_ref = self.client.collection("users").document(loser_uid)
        ph_repo = self.point_history_repo

        # Effective score: prefer request.score, fall back to stored score
        effective_score = request.score or match.score

        # A match is a walkover/retirement if explicitly flagged OR if the effective
        # score (which may come from the first submitter) has retired=True.
        is_walkover = request.walkover or (effective_score is not None and effective_score.retired)

        result_holder: dict[str, Any] = {}

        @firestore.transactional
        def _scoring_txn(txn: firestore.Transaction) -> None:
            # --- READS (must precede all writes) ---
            winner_snap = cast(firestore.DocumentSnapshot, winner_ref.get(transaction=txn))
            loser_snap = cast(firestore.DocumentSnapshot, loser_ref.get(transaction=txn))

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

            # Streak + personal best fields (CH-5)
            winner_current_streak = int(winner_ranking.get("currentStreak", 0))
            winner_best_streak = int(winner_ranking.get("bestStreak", 0))
            winner_personal_best = (
                int(winner_ranking["personalBest"])
                if winner_ranking.get("personalBest") is not None
                else None
            )
            loser_current_streak = int(loser_ranking.get("currentStreak", 0))
            loser_best_streak = int(loser_ranking.get("bestStreak", 0))

            result_holder["winner_pts_before"] = winner_pts
            result_holder["loser_pts_before"] = loser_pts
            result_holder["winner_tier_before"] = winner_tier
            result_holder["loser_tier_before"] = loser_tier
            result_holder["winner_name"] = winner_data.get("name", "")
            result_holder["winner_area"] = (winner_data.get("preferences") or {}).get("area")

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

            # Streak + personal best computation (CH-5)
            # Only update on non-walkover matches
            new_w_personal_best: int | None
            if not is_walkover:
                new_w_streak, new_w_best_streak = update_streak_on_win(
                    winner_current_streak, winner_best_streak
                )
                _, new_w_personal_best = check_personal_best(
                    scoring.winner_new_pts, winner_personal_best
                )
                new_l_streak, new_l_best_streak = update_streak_on_loss(
                    loser_current_streak, loser_best_streak
                )
            else:
                # Walkover/retirement: no streak or PB changes
                new_w_streak = winner_current_streak
                new_w_best_streak = winner_best_streak
                new_w_personal_best = winner_personal_best
                new_l_streak = loser_current_streak
                new_l_best_streak = loser_best_streak

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

            # 2. Winner ranking + playTab + streak/PB
            winner_updates: dict[str, Any] = {
                _ranking_field(sport_value, "pts"): scoring.winner_new_pts,
                _ranking_field(sport_value, "tier"): scoring.winner_new_tier.value,
                _ranking_field(sport_value, "lastUpdated"): now,
                _ranking_field(sport_value, "currentStreak"): new_w_streak,
                _ranking_field(sport_value, "bestStreak"): new_w_best_streak,
                "playTab.state": "DISCOVERY",
                "playTab.activeMatchId": None,
                "playTab.updatedAt": now,
            }
            if new_w_personal_best is not None:
                winner_updates[_ranking_field(sport_value, "personalBest")] = new_w_personal_best
            txn.update(winner_ref, winner_updates)

            # 3. Loser ranking + playTab + streak
            txn.update(
                loser_ref,
                {
                    _ranking_field(sport_value, "pts"): scoring.loser_new_pts,
                    _ranking_field(sport_value, "tier"): scoring.loser_new_tier.value,
                    _ranking_field(sport_value, "lastUpdated"): now,
                    _ranking_field(sport_value, "currentStreak"): new_l_streak,
                    _ranking_field(sport_value, "bestStreak"): new_l_best_streak,
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

        # Fire-and-forget: write upset ticker event outside the transaction
        if not is_walkover:
            self._maybe_write_upset_ticker(
                winner_uid=winner_uid,
                winner_name=result_holder.get("winner_name", ""),
                winner_tier=result_holder["winner_tier_before"],
                loser_tier=result_holder["loser_tier_before"],
                winner_delta=scoring.winner_delta.total,
                sport=sport,
                winner_area=result_holder.get("winner_area"),
                now=now,
            )
        is_winner = uid == winner_uid
        your_delta = scoring.winner_delta if is_winner else scoring.loser_delta
        scoring_payload = ScoringPayload(
            sport=sport,
            your_pts_before=result_holder["winner_pts_before"]
            if is_winner
            else result_holder["loser_pts_before"],
            your_pts_after=scoring.winner_new_pts if is_winner else scoring.loser_new_pts,
            delta=your_delta.total,
            breakdown=ScoringBreakdown(
                base_win=your_delta.base,
                upset_bonus=your_delta.upset_bonus,
                elo_bonus=your_delta.elo_bonus,
                penalty=your_delta.penalty,
            ),
            tier_before=result_holder["winner_tier_before"]
            if is_winner
            else result_holder["loser_tier_before"],
            tier_after=scoring.winner_new_tier if is_winner else scoring.loser_new_tier,
            tier_crossed=scoring.winner_tier_crossed if is_winner else scoring.loser_tier_crossed,
        )
        return VerifyScoreResponse(
            match_id=match_id,
            status=MatchStatusEnum.COMPLETED,
            winner_uid=winner_uid,
            loser_uid=loser_uid,
            winner_delta=scoring.winner_delta.total,
            loser_delta=scoring.loser_delta.total,
            winner_new_pts=scoring.winner_new_pts,
            loser_new_pts=scoring.loser_new_pts,
            scoring=scoring_payload,
        )

    # -------------------------------------------------------------------------
    # Upset ticker event (fire-and-forget)
    # -------------------------------------------------------------------------

    def _maybe_write_upset_ticker(
        self,
        *,
        winner_uid: str,
        winner_name: str,
        winner_tier: TierEnum,
        loser_tier: TierEnum,
        winner_delta: int,
        sport: Any,
        winner_area: int | None,
        now: datetime,
    ) -> None:
        if TIER_ORDER[winner_tier] >= TIER_ORDER[loser_tier]:
            return

        if self.ticker_repo is None or self.region_config_repo is None:
            return

        try:
            region_config = self.region_config_repo.get()
            region = region_config.mapping.get(str(winner_area)) if winner_area else None
            if not region:
                logger.warning("Skipping upset ticker: no region mapping for area %s", winner_area)
                return

            event = TickerEvent(
                type=TickerEventTypeEnum.UPSET,
                sport=sport,
                region=region,
                created_at=now,
                expires_at=now + timedelta(hours=_TICKER_TTL_HOURS),
                winner_uid=winner_uid,
                winner_name=winner_name,
                loser_tier=loser_tier,
                delta=winner_delta,
            )
            self.ticker_repo.add(event)
        except Exception:
            logger.exception("Failed to write upset ticker event (non-fatal)")
