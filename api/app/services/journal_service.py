"""
JournalService - Business logic for Tab 2 IMPROVE.

Handles:
- Journal entry creation (atomic transaction: entry doc + journalRecent cache update)
- Journal entry updates (partial, field-level)
- Entry listing (thin delegation to JournalRepo)
- Dashboard stats computation (compute-on-read via StatsRepo)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.enums import JournalEntryTypeEnum
from app.models.journal import (
    CreateJournalEntryRequest,
    CreateJournalEntryResponse,
    JournalEntry,
    MatchReflection,
    UpdateJournalEntryRequest,
)
from app.models.stats import NorthStarGoal, UserStats
from app.repos.journal_repo import JournalRepo
from app.repos.mappers import _parse_north_star_goal
from app.repos.matches_repo import MatchesRepo
from app.repos.stats_repo import StatsRepo
from app.repos.users_repo import UsersRepo

logger = logging.getLogger(__name__)

_JOURNAL_RECENT_MAX = 10


def _reflection_to_dict(reflection: MatchReflection | None) -> dict | None:
    """Serialize MatchReflection to a Firestore-ready camelCase dict."""
    if reflection is None:
        return None
    return {
        "wentWell": reflection.went_well,
        "wentWrong": reflection.went_wrong,
        "opponentWeak": reflection.opponent_weak,
        "opponentStrong": reflection.opponent_strong,
        "aiSummary": reflection.ai_summary,
    }


class JournalService:
    """Service for Tab 2 IMPROVE business logic."""

    def __init__(
        self,
        users_repo: UsersRepo,
        journal_repo: JournalRepo,
        matches_repo: MatchesRepo,
        firestore_client: firestore.Client,
    ):
        self.users_repo = users_repo
        self.journal_repo = journal_repo
        self.matches_repo = matches_repo
        self.client = firestore_client
        self.stats_repo = StatsRepo()

    # ===== POST /me/journal =====

    def create_entry(
        self, uid: str, request: CreateJournalEntryRequest
    ) -> CreateJournalEntryResponse:
        """
        Create a journal entry.

        Atomically writes the journal entry document and prepends a
        JournalEntrySummary to the journalRecent cache on the user doc
        (capped at _JOURNAL_RECENT_MAX entries, ordered newest-first).

        Match denormalization is lenient: if the match doc is missing or the
        user is not a participant we log a warning and continue rather than
        blocking the write.
        """
        user_doc = self.users_repo.get_user_doc(uid)
        if not user_doc:
            raise ValueError("User not found")

        now = datetime.now(timezone.utc)

        # Optionally denormalize result from match doc (score_text requires a
        # score-formatter utility — deferred to a future task).
        score_text = request.score_text
        result = request.result

        if request.entry_type == JournalEntryTypeEnum.MATCH and request.match_id:
            match = self.matches_repo.get_by_id(request.match_id)
            if match is None:
                logger.warning(
                    "create_entry: match_id=%s not found for uid=%s",
                    request.match_id,
                    uid,
                )
            else:
                if uid not in match.participant_uids:
                    logger.warning(
                        "create_entry: uid=%s is not a participant in match_id=%s",
                        uid,
                        request.match_id,
                    )
                # Denormalize result from match if the caller did not supply one
                if result is None and match.result_by_user:
                    result = match.result_by_user.get(uid)

        # Build Firestore entry doc (camelCase)
        entry_data: dict = {
            "title": request.title,
            "body": request.body,
            "tags": request.tags,
            "createdAt": now,
            "matchId": request.match_id,
            "sport": request.sport.value if request.sport else None,
            "visibility": request.visibility.value,
            "entryType": request.entry_type.value,
            "durationMinutes": request.duration_minutes,
            "trainingFocus": [f.value for f in request.training_focus],
            "reflection": None,
            "scoreText": score_text,
            "result": result.value if result else None,
        }

        # Pre-allocate the DocumentReference so we have the entry ID before
        # entering the transaction (needed to build the summary dict).
        entry_ref = (
            self.client.collection("users").document(uid).collection("journalEntries").document()
        )
        entry_id = entry_ref.id

        new_summary = {
            "entryId": entry_id,
            "createdAt": now,
            "title": request.title,
            "matchId": request.match_id,
            "sport": request.sport.value if request.sport else None,
            "entryType": request.entry_type.value,
        }

        user_ref = self.client.collection("users").document(uid)
        transaction = self.client.transaction()

        @firestore.transactional
        def _create_txn(txn):
            # Read journalRecent inside the transaction so the prepend+cap is
            # based on the value at transaction commit time (not at read time).
            snap = user_ref.get(transaction=txn)
            current_recent = (snap.to_dict() or {}).get("journalRecent", []) or []

            updated_recent = [new_summary] + current_recent
            updated_recent = updated_recent[:_JOURNAL_RECENT_MAX]

            txn.set(entry_ref, entry_data)
            txn.update(user_ref, {"journalRecent": updated_recent})

        _create_txn(transaction)

        return CreateJournalEntryResponse(entry_id=entry_id, created_at=now)

    # ===== PATCH /me/journal/{entry_id} =====

    def update_entry(self, uid: str, entry_id: str, request: UpdateJournalEntryRequest) -> None:
        """
        Partially update a journal entry.

        Only fields explicitly set (non-None) in the request are written.
        The entry must exist and belong to the requesting user.
        """
        entry = self.journal_repo.get_entry(uid, entry_id)
        if entry is None:
            raise ValueError(f"Journal entry {entry_id!r} not found")

        if entry.uid != uid:
            raise ValueError("Entry does not belong to this user")

        updates: dict = {}

        if request.reflection is not None:
            updates["reflection"] = _reflection_to_dict(request.reflection)

        if request.tags is not None:
            updates["tags"] = request.tags

        if request.body is not None:
            updates["body"] = request.body

        if not updates:
            return

        self.journal_repo.update_entry(uid, entry_id, updates)

    # ===== GET /me/journal =====

    def list_entries(
        self, uid: str, limit: int = 20, cursor: Optional[dict] = None
    ) -> list[JournalEntry]:
        """List journal entries for a user. Thin delegation to JournalRepo."""
        return self.journal_repo.list_entries(uid, limit=limit, cursor=cursor)

    # ===== GET /me/improve/stats =====

    def get_dashboard_stats(self, uid: str) -> UserStats:
        """
        Compute dashboard stats for a user (compute-on-read).

        Reads the user's private profile (which already contains cached
        journal summaries and completed-match summaries) and aggregates
        stats without any additional Firestore reads.

        Returns sensible defaults (all zeros) for users with no activity.
        """
        profile = self.users_repo.get_private_profile(uid)
        if profile is None:
            raise ValueError("User not found")

        return self.stats_repo.compute_user_stats(profile)

    # ===== PUT /me/improve/north-star =====

    def set_north_star(
        self,
        uid: str,
        goal_text: str,
        target_date: datetime | None = None,
    ) -> NorthStarGoal:
        """
        Overwrite the user's North Star goal.

        Always resets progressPct to 0.0 and stamps a new createdAt.
        """
        now = datetime.now(timezone.utc)
        goal_data = {
            "goalText": goal_text,
            "progressPct": 0.0,
            "createdAt": now,
            "targetDate": target_date,
        }
        self.client.collection("users").document(uid).update({"northStarGoal": goal_data})
        return NorthStarGoal(
            goal_text=goal_text,
            progress_pct=0.0,
            created_at=now,
            target_date=target_date,
        )

    # ===== GET /me/improve/north-star =====

    def get_north_star(self, uid: str) -> NorthStarGoal | None:
        """
        Return the user's current North Star goal, or None if not set.
        """
        user_doc = self.users_repo.get_user_doc(uid)
        if not user_doc:
            return None
        return _parse_north_star_goal(user_doc.get("northStarGoal"))

    # ===== Scouting pipeline (stub) =====

    def aggregate_opponent_tags(self, uid: str, opponent_uid: str) -> dict:
        """
        Aggregate opponent weakness/strength tags from all journal entries.

        # TODO: Query journalEntries where matchId references a match that
        #       included opponent_uid, collect reflection.opponent_weak and
        #       reflection.opponent_strong across all entries, and return
        #       aggregated tag frequency counts for the scouting pipeline.
        """
        return {"weak": [], "strong": []}
