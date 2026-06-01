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

from app.logging import log_analytics_event
from app.models.common import MatchScore
from app.models.enums import (
    MatchResultEnum,
    MatchStatusEnum,
    MatchTypeEnum,
    PlayNotificationIntentTypeEnum,
    PlayTabStateEnum,
    PointHistoryReasonEnum,
    TierEnum,
    TickerEventTypeEnum,
)
from app.models.notification import PlayNotificationIntent
from app.repos.notification_intent_repo import NotificationIntentRepo
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
from app.models.region_config import RegionConfig
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
STREAK_MILESTONE_THRESHOLDS: frozenset[int] = frozenset({3, 5, 10, 20})


def get_region_for_user(area_code: int | None, region_config: RegionConfig) -> str | None:
    """Map a user's area code to a region string via the regions config.

    Returns the region string (e.g. 'athens', 'south_london') if found,
    or None if area_code is falsy (None or 0) or not in the mapping.
    """
    if not area_code:
        return None
    return region_config.mapping.get(str(area_code))


def _format_short_name(full_name: str) -> str:
    """Format 'Firstname Lastname' as 'Firstname L.' for ticker display."""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return parts[0] if parts else ""


def _score_to_doc(
    score: MatchScore,
    winner_uid: str | None,
    winner_team: str | None = None,
) -> dict[str, Any]:
    """Serialize a ``MatchScore`` into Firestore camelCase form.

    For singles, ``winner_uid`` is set and ``winner_team`` is ``None``. For
    doubles (DBL-5) the inverse is true. Both fields are always present in
    the document so consumers don't have to guess which shape to expect.
    """
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
        "winnerTeam": winner_team,
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
        notification_intent_repo: NotificationIntentRepo | None = None,
    ):
        self.matches_repo = matches_repo
        self.users_repo = users_repo
        self.point_history_repo = point_history_repo
        self.tier_config_repo = tier_config_repo
        self.client = firestore_client
        self.ticker_repo = ticker_repo
        self.region_config_repo = region_config_repo
        self.notification_intent_repo = notification_intent_repo

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def verify_score(
        self,
        uid: str,
        match_id: str,
        request: VerifyScoreRequest,
    ) -> VerifyScoreResponse:
        """Submit or confirm a match result, running inline scoring on confirmation.

        For singles the legacy ``winner_uid`` payload is used and inline
        scoring runs on confirmation. For doubles (DBL-5) the request must
        carry ``winner_team`` (``'A'`` or ``'B'``); confirmation must come
        from a player on the *opposing* team and there is no inline scoring
        — the match simply transitions to COMPLETED for all 4 participants.
        """
        match = self.matches_repo.get_by_id(match_id)
        if match is None:
            raise ValueError(f"Match {match_id} not found")

        if uid not in match.participant_uids:
            raise PermissionError("You are not a participant in this match")

        if match.status not in (MatchStatusEnum.SCHEDULED, MatchStatusEnum.PENDING_CONFIRMATION):
            raise ValueError(f"Cannot submit result for a match with status '{match.status}'")

        now = datetime.now(timezone.utc)

        if match.match_type == MatchTypeEnum.DOUBLES:
            return self._verify_score_doubles(uid, match_id, match, request, now)

        # Singles (legacy path)
        if request.winner_team is not None:
            raise ValueError("winner_team is only valid for doubles matches; use winner_uid")
        if request.winner_uid is None:
            raise ValueError("winner_uid is required for singles matches")
        if request.winner_uid not in match.participant_uids:
            raise ValueError("winner_uid is not a participant in this match")

        if match.status == MatchStatusEnum.SCHEDULED:
            return self._first_submission(uid, match_id, match, request, now)
        else:
            return self._second_submission(uid, match_id, match, request, now)

    # -------------------------------------------------------------------------
    # Doubles (DBL-5)
    # -------------------------------------------------------------------------

    def _verify_score_doubles(
        self,
        uid: str,
        match_id: str,
        match: Match,
        request: VerifyScoreRequest,
        now: datetime,
    ) -> VerifyScoreResponse:
        if request.winner_uid is not None:
            raise ValueError("winner_uid is not valid for doubles matches; use winner_team")
        if request.winner_team is None:
            raise ValueError("winner_team is required for doubles matches")
        if request.winner_team not in {"A", "B"}:
            raise ValueError("winner_team must be 'A' or 'B'")

        # Build {uid -> team} from the participants array. The match
        # validator (DBL-2) already guarantees doubles matches carry exactly
        # 4 participants split 2/2 across teams A and B.
        team_by_uid = {p.uid: p.team for p in match.participants}
        submitter_team = team_by_uid.get(uid)
        if submitter_team not in {"A", "B"}:
            # Defensive: a participant in a doubles match must have a team
            # label. If the document predates DBL-2 and this is missing we
            # cannot safely route the confirmation — bail out.
            raise ValueError("Doubles participant is missing a team label")

        if match.status == MatchStatusEnum.SCHEDULED:
            return self._first_submission_doubles(
                uid, match_id, match, request, submitter_team, team_by_uid, now
            )
        return self._second_submission_doubles(
            uid, match_id, match, request, submitter_team, team_by_uid, now
        )

    def _first_submission_doubles(
        self,
        uid: str,
        match_id: str,
        match: Match,
        request: VerifyScoreRequest,
        submitter_team: str,
        team_by_uid: dict[str, str | None],
        now: datetime,
    ) -> VerifyScoreResponse:
        winner_team = request.winner_team
        assert winner_team is not None  # narrowed for mypy
        loser_team = "B" if winner_team == "A" else "A"
        # Per-player resultByUser map so /me/state can render win/loss for
        # any participant without needing to recompute team membership.
        result_by_user = {
            p_uid: (MatchResultEnum.WIN if t == winner_team else MatchResultEnum.LOSS)
            for p_uid, t in team_by_uid.items()
        }

        match_ref = self.client.collection("matches").document(match_id)
        # Always persist the winner_team on first submission, even when the
        # caller did not provide a score payload. Without this, a later
        # opposing-team submission would have no stored winner_team to
        # compare against and a genuine disagreement would be silently
        # accepted as a confirmation instead of routed to MATCH_DISPUTED.
        if request.score is not None:
            score_doc: dict[str, Any] = _score_to_doc(request.score, None, winner_team)
        else:
            score_doc = {
                "sets": [],
                "winnerUid": None,
                "winnerTeam": winner_team,
                "retired": False,
            }

        transaction = self.client.transaction()

        @firestore.transactional
        def _txn(txn: firestore.Transaction) -> None:
            updates: dict[str, Any] = {
                "status": MatchStatusEnum.PENDING_CONFIRMATION,
                "resultByUser": result_by_user,
                "resultSubmittedBy": firestore.ArrayUnion([uid]),
                "score": score_doc,
            }
            txn.update(match_ref, updates)

            # Update playTab.state for all 4 participants:
            #  - submitter → POST_MATCH_WAITING_OPPONENT
            #  - other 3   → POST_MATCH_CONFIRM_REQUIRED
            for p_uid in team_by_uid:
                user_ref = self.client.collection("users").document(p_uid)
                state = (
                    PlayTabStateEnum.POST_MATCH_WAITING_OPPONENT.value
                    if p_uid == uid
                    else PlayTabStateEnum.POST_MATCH_CONFIRM_REQUIRED.value
                )
                txn.update(
                    user_ref,
                    {
                        "playTab.state": state,
                        "playTab.activeMatchId": match_id,
                        "playTab.updatedAt": now,
                    },
                )

        _txn(transaction)

        log_analytics_event(
            logger,
            event="score_submitted",
            uid=uid,
            created_at=now.replace(tzinfo=None).isoformat() + "Z",
            sport=match.sport.value,
            match_type=match.match_type.value,
            venue_present=(match.court_id is not None or match.venue_ref is not None),
            match_id=match_id,
        )

        for p_uid in team_by_uid:
            if p_uid == uid:
                continue
            self._emit_notification_intent(
                PlayNotificationIntent(
                    type=PlayNotificationIntentTypeEnum.SCORE_CONFIRM_REQUIRED,
                    target_uid=p_uid,
                    title="Score submitted",
                    body="Confirm the match result",
                    match_id=match_id,
                    dedupe_key=f"score_confirm_required:{match_id}:{p_uid}",
                    created_at=now,
                )
            )

        return VerifyScoreResponse(
            match_id=match_id,
            status=MatchStatusEnum.PENDING_CONFIRMATION,
            winner_uid="",
            loser_uid="",
            winner_team=winner_team,
            loser_team=loser_team,
        )

    def _second_submission_doubles(
        self,
        uid: str,
        match_id: str,
        match: Match,
        request: VerifyScoreRequest,
        submitter_team: str,
        team_by_uid: dict[str, str | None],
        now: datetime,
    ) -> VerifyScoreResponse:
        winner_team = request.winner_team
        assert winner_team is not None
        loser_team = "B" if winner_team == "A" else "A"

        # Identify the original submitter from resultSubmittedBy. If for any
        # reason it's empty (legacy doc) we treat the call as a first
        # submission instead so the confirmer's vote at least gets recorded.
        original_submitter = match.result_submitted_by[0] if match.result_submitted_by else None
        original_submitter_team = (
            team_by_uid.get(original_submitter) if original_submitter else None
        )
        if original_submitter is not None and submitter_team == original_submitter_team:
            # Same-team confirmation is not allowed — the issue requires the
            # confirmation to come from a player on the OPPOSING team. We
            # surface this as a 409 (the router maps ValueError → 409).
            raise ValueError("Confirmation must come from a player on the opposing team")

        stored_winner_team = match.score.winner_team if match.score else None
        is_dispute = stored_winner_team is not None and stored_winner_team != winner_team

        if is_dispute:
            return self._dispute_doubles(
                uid, match_id, match, winner_team, loser_team, team_by_uid, now
            )

        return self._complete_with_scoring_doubles(
            uid,
            match_id,
            match,
            request,
            winner_team,
            loser_team,
            team_by_uid,
            now,
        )

    def _dispute_doubles(
        self,
        uid: str,
        match_id: str,
        match: Match,
        winner_team: str,
        loser_team: str,
        team_by_uid: dict[str, str | None],
        now: datetime,
    ) -> VerifyScoreResponse:
        match_ref = self.client.collection("matches").document(match_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def _txn(txn: firestore.Transaction) -> None:
            txn.update(
                match_ref,
                {
                    "status": MatchStatusEnum.DISPUTED,
                    "resultSubmittedBy": firestore.ArrayUnion([uid]),
                },
            )
            for p_uid in team_by_uid:
                user_ref = self.client.collection("users").document(p_uid)
                txn.update(
                    user_ref,
                    {
                        "playTab.state": PlayTabStateEnum.MATCH_DISPUTED.value,
                        "playTab.updatedAt": now,
                    },
                )

        _txn(transaction)

        log_analytics_event(
            logger,
            event="match_disputed",
            uid=uid,
            created_at=now.replace(tzinfo=None).isoformat() + "Z",
            sport=match.sport.value,
            match_type=match.match_type.value,
            venue_present=(match.court_id is not None or match.venue_ref is not None),
            match_id=match_id,
        )

        return VerifyScoreResponse(
            match_id=match_id,
            status=MatchStatusEnum.DISPUTED,
            winner_uid="",
            loser_uid="",
            winner_team=winner_team,
            loser_team=loser_team,
        )

    def _complete_with_scoring_doubles(
        self,
        uid: str,
        match_id: str,
        match: Match,
        request: VerifyScoreRequest,
        winner_team: str,
        loser_team: str,
        team_by_uid: dict[str, str | None],
        now: datetime,
    ) -> VerifyScoreResponse:
        """Doubles equivalent of ``_complete_with_scoring``.

        Scoring is computed per-player by treating the *opposing pair* as a
        single notional opponent: each player is scored against the average
        pts of the two opponents. We do this with 4 calls to
        ``compute_match_scoring`` (one per player) so that per-player tier
        comparisons (and the upset bonus they unlock) still work without
        having to invent a "team tier".

        Tier args use the player's own tier and the highest-tier opponent's
        tier — this matches the singles semantics where the upset bonus is
        triggered by tier diff against the actual opponent, not an averaged
        proxy.
        """
        tier_config = self.tier_config_repo.get()
        sport = match.sport
        sport_value = sport.value
        match_ref = self.client.collection("matches").document(match_id)
        ph_repo = self.point_history_repo

        winner_uids = [p_uid for p_uid, t in team_by_uid.items() if t == winner_team]
        loser_uids = [p_uid for p_uid, t in team_by_uid.items() if t == loser_team]

        # Defensive: doubles validator already guarantees 2/2, but we depend
        # on it explicitly for averaging below.
        if len(winner_uids) != 2 or len(loser_uids) != 2:
            raise ValueError("Doubles match must have exactly 2 players per team")

        winner_refs = {
            p_uid: self.client.collection("users").document(p_uid) for p_uid in winner_uids
        }
        loser_refs = {
            p_uid: self.client.collection("users").document(p_uid) for p_uid in loser_uids
        }

        effective_score = request.score or match.score
        is_walkover = request.walkover or (effective_score is not None and effective_score.retired)

        result_by_user = {
            p_uid: (MatchResultEnum.WIN if t == winner_team else MatchResultEnum.LOSS)
            for p_uid, t in team_by_uid.items()
        }

        result_holder: dict[str, Any] = {}

        @firestore.transactional
        def _scoring_txn(txn: firestore.Transaction) -> None:
            # --- READS (must precede all writes) ---
            winner_snaps = {
                p_uid: cast(firestore.DocumentSnapshot, ref.get(transaction=txn))
                for p_uid, ref in winner_refs.items()
            }
            loser_snaps = {
                p_uid: cast(firestore.DocumentSnapshot, ref.get(transaction=txn))
                for p_uid, ref in loser_refs.items()
            }

            def _extract(
                snap: firestore.DocumentSnapshot,
            ) -> dict[str, Any]:
                data = snap.to_dict() or {}
                ranking = (data.get("rankings") or {}).get(sport_value) or {}
                return {
                    "data": data,
                    "ranking": ranking,
                    "pts": int(ranking.get("pts", _DEFAULT_PTS)),
                    "tier": TierEnum(ranking.get("tier", _DEFAULT_TIER)),
                    "reg_tier": TierEnum(
                        ranking.get("registrationTier", ranking.get("tier", _DEFAULT_TIER))
                    ),
                    "current_streak": int(ranking.get("currentStreak", 0)),
                    "best_streak": int(ranking.get("bestStreak", 0)),
                    "personal_best": (
                        int(ranking["personalBest"])
                        if ranking.get("personalBest") is not None
                        else None
                    ),
                    "name": data.get("name", ""),
                    "area": (data.get("preferences") or {}).get("area"),
                    "feed_opt_out": (data.get("preferences") or {}).get("feedOptOut", False),
                }

            winners = {p_uid: _extract(snap) for p_uid, snap in winner_snaps.items()}
            losers = {p_uid: _extract(snap) for p_uid, snap in loser_snaps.items()}

            # Average opposing pts (for the per-player elo / penalty calc).
            avg_loser_pts = sum(v["pts"] for v in losers.values()) // len(losers)
            avg_winner_pts = sum(v["pts"] for v in winners.values()) // len(winners)

            # Pick the highest-tier opponent for tier comparison so the upset
            # bonus fires when EITHER opposing player is in a higher tier than
            # the scored player. Mirrors the singles "did I beat someone
            # ranked above me?" intent.
            def _highest_tier(values: list[TierEnum]) -> TierEnum:
                return max(values, key=lambda t: TIER_ORDER[t])

            top_loser_tier = _highest_tier([v["tier"] for v in losers.values()])
            top_winner_tier = _highest_tier([v["tier"] for v in winners.values()])

            # --- COMPUTE per-player scoring ---
            winner_results: dict[str, Any] = {}
            for p_uid, info in winners.items():
                scoring = compute_match_scoring(
                    winner_pts=info["pts"],
                    loser_pts=avg_loser_pts,
                    winner_tier=info["tier"],
                    loser_tier=top_loser_tier,
                    winner_reg_tier=info["reg_tier"],
                    loser_reg_tier=info["reg_tier"],  # unused for winner
                    tier_config=tier_config,
                    walkover=is_walkover,
                    retired=effective_score.retired if effective_score else False,
                )
                winner_results[p_uid] = scoring

            loser_results: dict[str, Any] = {}
            for p_uid, info in losers.items():
                scoring = compute_match_scoring(
                    winner_pts=avg_winner_pts,
                    loser_pts=info["pts"],
                    winner_tier=top_winner_tier,
                    loser_tier=info["tier"],
                    winner_reg_tier=info["reg_tier"],  # unused for loser
                    loser_reg_tier=info["reg_tier"],
                    tier_config=tier_config,
                    walkover=is_walkover,
                    retired=effective_score.retired if effective_score else False,
                )
                loser_results[p_uid] = scoring

            # Streak / PB updates per player
            new_streaks: dict[str, tuple[int, int]] = {}
            new_pbs: dict[str, int | None] = {}
            is_new_best_map: dict[str, bool] = {}
            for p_uid, info in winners.items():
                if not is_walkover:
                    cur, best = update_streak_on_win(info["current_streak"], info["best_streak"])
                    is_new_best, new_pb = check_personal_best(
                        winner_results[p_uid].winner_new_pts, info["personal_best"]
                    )
                else:
                    cur, best = info["current_streak"], info["best_streak"]
                    is_new_best, new_pb = False, info["personal_best"]
                new_streaks[p_uid] = (cur, best)
                new_pbs[p_uid] = new_pb
                is_new_best_map[p_uid] = is_new_best

            for p_uid, info in losers.items():
                if not is_walkover:
                    cur, best = update_streak_on_loss(info["current_streak"], info["best_streak"])
                else:
                    cur, best = info["current_streak"], info["best_streak"]
                new_streaks[p_uid] = (cur, best)

            score_doc = (
                _score_to_doc(effective_score, None, winner_team) if effective_score else None
            )

            # --- WRITES ---
            # 1. Match
            match_updates: dict[str, Any] = {
                "status": MatchStatusEnum.COMPLETED,
                "finishedAt": now,
                "resultByUser": result_by_user,
                "resultSubmittedBy": firestore.ArrayUnion([uid]),
            }
            if score_doc is not None:
                match_updates["score"] = score_doc
            txn.update(match_ref, match_updates)

            # 2. Winners
            for p_uid, info in winners.items():
                scoring = winner_results[p_uid]
                cur, best = new_streaks[p_uid]
                user_updates: dict[str, Any] = {
                    _ranking_field(sport_value, "pts"): scoring.winner_new_pts,
                    _ranking_field(sport_value, "tier"): scoring.winner_new_tier.value,
                    _ranking_field(sport_value, "lastUpdated"): now,
                    _ranking_field(sport_value, "currentStreak"): cur,
                    _ranking_field(sport_value, "bestStreak"): best,
                    "playTab.state": PlayTabStateEnum.DISCOVERY.value,
                    "playTab.activeMatchId": None,
                    "playTab.updatedAt": now,
                }
                if new_pbs[p_uid] is not None:
                    user_updates[_ranking_field(sport_value, "personalBest")] = new_pbs[p_uid]
                txn.update(winner_refs[p_uid], user_updates)

            # 3. Losers
            for p_uid, info in losers.items():
                scoring = loser_results[p_uid]
                cur, best = new_streaks[p_uid]
                txn.update(
                    loser_refs[p_uid],
                    {
                        _ranking_field(sport_value, "pts"): scoring.loser_new_pts,
                        _ranking_field(sport_value, "tier"): scoring.loser_new_tier.value,
                        _ranking_field(sport_value, "lastUpdated"): now,
                        _ranking_field(sport_value, "currentStreak"): cur,
                        _ranking_field(sport_value, "bestStreak"): best,
                        "playTab.state": PlayTabStateEnum.DISCOVERY.value,
                        "playTab.activeMatchId": None,
                        "playTab.updatedAt": now,
                    },
                )

            # 4. pointHistory — skipped for walkover/retirement
            if not is_walkover:
                # Opponent_uid for doubles is recorded as the first opponent
                # in the opposing team (deterministic alphabetical order); the
                # remaining opponent identity is recoverable via the match doc.
                sorted_winner_uids = sorted(winner_uids)
                sorted_loser_uids = sorted(loser_uids)
                for p_uid, info in winners.items():
                    scoring = winner_results[p_uid]
                    entry = PointHistoryEntry(
                        entry_id="",
                        sport=sport,
                        pts=scoring.winner_new_pts,
                        delta=scoring.winner_delta.total,
                        reason=PointHistoryReasonEnum.MATCH_DOUBLES_WIN,
                        match_id=match_id,
                        opponent_uid=sorted_loser_uids[0],
                        opponent_pts_before=avg_loser_pts,
                        league_id=match.league_id,
                        created_at=now,
                        tier_before=info["tier"],
                        tier_after=scoring.winner_new_tier,
                    )
                    ph_repo.add_entry_in_transaction(txn, p_uid, entry)
                for p_uid, info in losers.items():
                    scoring = loser_results[p_uid]
                    entry = PointHistoryEntry(
                        entry_id="",
                        sport=sport,
                        pts=scoring.loser_new_pts,
                        delta=scoring.loser_delta.total,
                        reason=PointHistoryReasonEnum.MATCH_DOUBLES_LOSS,
                        match_id=match_id,
                        opponent_uid=sorted_winner_uids[0],
                        opponent_pts_before=avg_winner_pts,
                        league_id=match.league_id,
                        created_at=now,
                        tier_before=info["tier"],
                        tier_after=scoring.loser_new_tier,
                    )
                    ph_repo.add_entry_in_transaction(txn, p_uid, entry)

            # Stash for post-txn ticker emission and response building
            result_holder["winners"] = winners
            result_holder["losers"] = losers
            result_holder["winner_results"] = winner_results
            result_holder["loser_results"] = loser_results
            result_holder["new_streaks"] = new_streaks
            result_holder["new_pbs"] = new_pbs
            result_holder["is_new_best_map"] = is_new_best_map

        _scoring_txn(self.client.transaction())

        log_analytics_event(
            logger,
            event="score_confirmed",
            uid=uid,
            created_at=now.replace(tzinfo=None).isoformat() + "Z",
            sport=match.sport.value,
            match_type=match.match_type.value,
            venue_present=(match.court_id is not None or match.venue_ref is not None),
            match_id=match_id,
        )

        winners = result_holder["winners"]
        losers = result_holder["losers"]
        winner_results = result_holder["winner_results"]
        loser_results = result_holder["loser_results"]
        new_streaks = result_holder["new_streaks"]
        is_new_best_map = result_holder["is_new_best_map"]

        # Fire-and-forget tickers (per-player). Upset ticker is intentionally
        # NOT emitted for doubles in DBL-6 — the comparison rule for a 2-vs-2
        # upset is still TBD.
        # TODO(DBL-Upset-Ticker): defer upset ticker to follow-up issue —
        # doubles upset comparison rule TBD.
        if not is_walkover:
            for p_uid, info in winners.items():
                scoring = winner_results[p_uid]
                self._maybe_write_tier_crossed_ticker(
                    uid=p_uid,
                    name=info["name"],
                    area=info["area"],
                    tier_before=info["tier"],
                    tier_after=scoring.winner_new_tier,
                    sport=sport,
                    now=now,
                    feed_opt_out=info["feed_opt_out"],
                )
                self._maybe_write_personal_best_ticker(
                    winner_uid=p_uid,
                    winner_name=info["name"],
                    winner_area=info["area"],
                    new_pts=scoring.winner_new_pts,
                    previous_best=info["personal_best"],
                    is_new_best=is_new_best_map.get(p_uid, False),
                    sport=sport,
                    now=now,
                    feed_opt_out=info["feed_opt_out"],
                )
                self._maybe_write_win_streak_ticker(
                    winner_uid=p_uid,
                    winner_name=info["name"],
                    winner_area=info["area"],
                    streak=new_streaks[p_uid][0],
                    sport=sport,
                    now=now,
                    feed_opt_out=info["feed_opt_out"],
                )
            for p_uid, info in losers.items():
                scoring = loser_results[p_uid]
                self._maybe_write_tier_crossed_ticker(
                    uid=p_uid,
                    name=info["name"],
                    area=info["area"],
                    tier_before=info["tier"],
                    tier_after=scoring.loser_new_tier,
                    sport=sport,
                    now=now,
                    feed_opt_out=info["feed_opt_out"],
                )

        # Build the calling user's ScoringPayload, mirroring the singles shape.
        caller_is_winner = uid in winners
        if caller_is_winner:
            caller_info = winners[uid]
            caller_scoring = winner_results[uid]
            caller_delta = caller_scoring.winner_delta
            caller_pts_after = caller_scoring.winner_new_pts
            caller_tier_after = caller_scoring.winner_new_tier
            caller_tier_crossed = caller_scoring.winner_tier_crossed
        else:
            caller_info = losers[uid]
            caller_scoring = loser_results[uid]
            caller_delta = caller_scoring.loser_delta
            caller_pts_after = caller_scoring.loser_new_pts
            caller_tier_after = caller_scoring.loser_new_tier
            caller_tier_crossed = caller_scoring.loser_tier_crossed

        scoring_payload = ScoringPayload(
            sport=sport,
            your_pts_before=caller_info["pts"],
            your_pts_after=caller_pts_after,
            delta=caller_delta.total,
            breakdown=ScoringBreakdown(
                base_win=caller_delta.base,
                upset_bonus=caller_delta.upset_bonus,
                elo_bonus=caller_delta.elo_bonus,
                penalty=caller_delta.penalty,
            ),
            tier_before=caller_info["tier"],
            tier_after=caller_tier_after,
            tier_crossed=caller_tier_crossed,
        )

        return VerifyScoreResponse(
            match_id=match_id,
            status=MatchStatusEnum.COMPLETED,
            winner_uid="",
            loser_uid="",
            winner_team=winner_team,
            loser_team=loser_team,
            scoring=scoring_payload,
        )

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
        # ``verify_score`` guards ensure winner_uid is set on the singles path.
        assert request.winner_uid is not None
        winner_uid: str = request.winner_uid
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
                "resultSubmittedBy": firestore.ArrayUnion([uid]),
            }
            if score_doc is not None:
                updates["score"] = score_doc
            txn.update(match_ref, updates)

        _txn(transaction)

        log_analytics_event(
            logger,
            event="score_submitted",
            uid=uid,
            created_at=now.replace(tzinfo=None).isoformat() + "Z",
            sport=match.sport.value,
            match_type=match.match_type.value,
            venue_present=(match.court_id is not None or match.venue_ref is not None),
            match_id=match_id,
        )

        # NOTE: singles play-tab state transitions on first submission are
        # intentionally left unchanged to preserve the legacy contract — the
        # POST_MATCH_* states are wired up only for doubles in DBL-5.

        non_submitter_uid = next(p for p in match.participant_uids if p != uid)
        self._emit_notification_intent(
            PlayNotificationIntent(
                type=PlayNotificationIntentTypeEnum.SCORE_CONFIRM_REQUIRED,
                target_uid=non_submitter_uid,
                title="Score submitted",
                body="Confirm the match result",
                match_id=match_id,
                dedupe_key=f"score_confirm_required:{match_id}:{non_submitter_uid}",
                created_at=now,
            )
        )

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
        assert request.winner_uid is not None
        winner_uid: str = request.winner_uid
        loser_uid = next(p for p in match.participant_uids if p != winner_uid)

        # INT-1: a singles result must be confirmed by the OTHER participant,
        # never the player who submitted it. Without this a single player could
        # submit and then confirm their own result, awarding points with no
        # opponent agreement. Mirrors the doubles opposing-party rule in
        # _second_submission_doubles. Empty result_submitted_by (legacy docs) is
        # treated leniently so the confirmation still records.
        if uid in match.result_submitted_by:
            raise ValueError("Confirmation must come from the opposing player")

        stored_winner_uid = match.score.winner_uid if match.score else None

        if stored_winner_uid is not None and stored_winner_uid != winner_uid:
            return self._dispute(uid, match_id, match, winner_uid, loser_uid, request, now)

        return self._complete_with_scoring(
            uid, match_id, match, request, winner_uid, loser_uid, now
        )

    def _dispute(
        self,
        uid: str,
        match_id: str,
        match: Match,
        winner_uid: str,
        loser_uid: str,
        request: VerifyScoreRequest,
        now: datetime,
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
                    "resultSubmittedBy": firestore.ArrayUnion([uid]),
                },
            )

        _txn(transaction)

        log_analytics_event(
            logger,
            event="match_disputed",
            uid=uid,
            created_at=now.replace(tzinfo=None).isoformat() + "Z",
            sport=match.sport.value,
            match_type=match.match_type.value,
            venue_present=(match.court_id is not None or match.venue_ref is not None),
            match_id=match_id,
        )

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
            result_holder["loser_name"] = loser_data.get("name", "")
            result_holder["loser_area"] = (loser_data.get("preferences") or {}).get("area")
            result_holder["winner_feed_opt_out"] = (winner_data.get("preferences") or {}).get(
                "feedOptOut", False
            )
            result_holder["loser_feed_opt_out"] = (loser_data.get("preferences") or {}).get(
                "feedOptOut", False
            )

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
                is_new_best, new_w_personal_best = check_personal_best(
                    scoring.winner_new_pts, winner_personal_best
                )
                result_holder["is_new_best"] = is_new_best
                result_holder["winner_personal_best_before"] = winner_personal_best
                result_holder["winner_new_streak"] = new_w_streak
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
                    "resultSubmittedBy": firestore.ArrayUnion([uid]),
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

        log_analytics_event(
            logger,
            event="score_confirmed",
            uid=uid,
            created_at=now.replace(tzinfo=None).isoformat() + "Z",
            sport=match.sport.value,
            match_type=match.match_type.value,
            venue_present=(match.court_id is not None or match.venue_ref is not None),
            match_id=match_id,
        )

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
                feed_opt_out=result_holder.get("winner_feed_opt_out", False),
            )
            self._maybe_write_tier_crossed_ticker(
                uid=winner_uid,
                name=result_holder.get("winner_name", ""),
                area=result_holder.get("winner_area"),
                tier_before=result_holder["winner_tier_before"],
                tier_after=scoring.winner_new_tier,
                sport=sport,
                now=now,
                feed_opt_out=result_holder.get("winner_feed_opt_out", False),
            )
            self._maybe_write_tier_crossed_ticker(
                uid=loser_uid,
                name=result_holder.get("loser_name", ""),
                area=result_holder.get("loser_area"),
                tier_before=result_holder["loser_tier_before"],
                tier_after=scoring.loser_new_tier,
                sport=sport,
                now=now,
                feed_opt_out=result_holder.get("loser_feed_opt_out", False),
            )
            self._maybe_write_personal_best_ticker(
                winner_uid=winner_uid,
                winner_name=result_holder.get("winner_name", ""),
                winner_area=result_holder.get("winner_area"),
                new_pts=scoring.winner_new_pts,
                previous_best=result_holder.get("winner_personal_best_before"),
                is_new_best=result_holder.get("is_new_best", False),
                sport=sport,
                now=now,
                feed_opt_out=result_holder.get("winner_feed_opt_out", False),
            )
            self._maybe_write_win_streak_ticker(
                winner_uid=winner_uid,
                winner_name=result_holder.get("winner_name", ""),
                winner_area=result_holder.get("winner_area"),
                streak=result_holder.get("winner_new_streak", 0),
                sport=sport,
                now=now,
                feed_opt_out=result_holder.get("winner_feed_opt_out", False),
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
    # Notification intents (fire-and-forget)
    # -------------------------------------------------------------------------

    def _emit_notification_intent(self, intent: PlayNotificationIntent) -> None:
        if self.notification_intent_repo is None:
            return
        try:
            self.notification_intent_repo.add_intent(intent)
        except Exception:
            logger.exception("Failed to write notification intent (non-fatal)")

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
        feed_opt_out: bool = False,
    ) -> None:
        if TIER_ORDER[winner_tier] >= TIER_ORDER[loser_tier]:
            return

        if feed_opt_out:
            return

        if self.ticker_repo is None or self.region_config_repo is None:
            return

        try:
            region_config = self.region_config_repo.get()
            region = get_region_for_user(winner_area, region_config)
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

    # -------------------------------------------------------------------------
    # Tier-crossed ticker event (fire-and-forget)
    # -------------------------------------------------------------------------

    def _maybe_write_tier_crossed_ticker(
        self,
        *,
        uid: str,
        name: str,
        area: int | None,
        tier_before: TierEnum,
        tier_after: TierEnum,
        sport: Any,
        now: datetime,
        feed_opt_out: bool = False,
    ) -> None:
        if tier_before == tier_after:
            return

        if feed_opt_out:
            return

        if self.ticker_repo is None or self.region_config_repo is None:
            return

        try:
            region_config = self.region_config_repo.get()
            region = get_region_for_user(area, region_config)
            if not region:
                logger.warning("Skipping tier_crossed ticker: no region mapping for area %s", area)
                return

            direction = "up" if TIER_ORDER[tier_after] > TIER_ORDER[tier_before] else "down"
            user_name = _format_short_name(name)

            event = TickerEvent(
                type=TickerEventTypeEnum.TIER_CROSSED,
                sport=sport,
                region=region,
                created_at=now,
                expires_at=now + timedelta(hours=_TICKER_TTL_HOURS),
                user_uid=uid,
                user_name=user_name,
                tier_before=tier_before,
                tier_after=tier_after,
                direction=direction,
            )
            self.ticker_repo.add(event)
        except Exception:
            logger.exception("Failed to write tier_crossed ticker event (non-fatal)")

    # -------------------------------------------------------------------------
    # Personal-best ticker event (fire-and-forget)
    # -------------------------------------------------------------------------

    def _maybe_write_personal_best_ticker(
        self,
        *,
        winner_uid: str,
        winner_name: str,
        winner_area: int | None,
        new_pts: int,
        previous_best: int | None,
        is_new_best: bool,
        sport: Any,
        now: datetime,
        feed_opt_out: bool = False,
    ) -> None:
        if not is_new_best:
            return

        if feed_opt_out:
            return

        if self.ticker_repo is None or self.region_config_repo is None:
            return

        try:
            region_config = self.region_config_repo.get()
            region = get_region_for_user(winner_area, region_config)
            if not region:
                logger.warning(
                    "Skipping personal_best ticker: no region mapping for area %s",
                    winner_area,
                )
                return

            user_name = _format_short_name(winner_name)

            event = TickerEvent(
                type=TickerEventTypeEnum.PERSONAL_BEST,
                sport=sport,
                region=region,
                created_at=now,
                expires_at=now + timedelta(hours=_TICKER_TTL_HOURS),
                user_uid=winner_uid,
                user_name=user_name,
                new_pts=new_pts,
                previous_best=previous_best if previous_best is not None else 0,
            )
            self.ticker_repo.add(event)
        except Exception:
            logger.exception("Failed to write personal_best ticker event (non-fatal)")

    # -------------------------------------------------------------------------
    # Win-streak milestone ticker event (fire-and-forget)
    # -------------------------------------------------------------------------

    def _maybe_write_win_streak_ticker(
        self,
        *,
        winner_uid: str,
        winner_name: str,
        winner_area: int | None,
        streak: int,
        sport: Any,
        now: datetime,
        feed_opt_out: bool = False,
    ) -> None:
        if streak not in STREAK_MILESTONE_THRESHOLDS:
            return

        if feed_opt_out:
            return

        if self.ticker_repo is None or self.region_config_repo is None:
            return

        try:
            region_config = self.region_config_repo.get()
            region = get_region_for_user(winner_area, region_config)
            if not region:
                logger.warning(
                    "Skipping win_streak ticker: no region mapping for area %s",
                    winner_area,
                )
                return

            user_name = _format_short_name(winner_name)

            event = TickerEvent(
                type=TickerEventTypeEnum.WIN_STREAK,
                sport=sport,
                region=region,
                created_at=now,
                expires_at=now + timedelta(hours=_TICKER_TTL_HOURS),
                user_uid=winner_uid,
                user_name=user_name,
                streak=streak,
            )
            self.ticker_repo.add(event)
        except Exception:
            logger.exception("Failed to write win_streak ticker event (non-fatal)")
