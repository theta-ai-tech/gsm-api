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
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.constants import (
    JOURNAL_CREATE_RATE_LIMIT_PER_HOUR,
    JOURNAL_LIST_DEFAULT_LIMIT,
    JOURNAL_RECENT_MAX,
)
from app.logging import log_analytics_event
from app.models.enums import JournalEntryTypeEnum
from app.models.journal import (
    CreateJournalEntryRequest,
    CreateJournalEntryResponse,
    JournalEntry,
    LoggableMatch,
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


class JournalRateLimitError(ValueError):
    """Raised when the per-user journal create rate limit is exceeded."""


class UnsupportedJournalFilterError(ValueError):
    """Raised when journal list filters are requested but not implemented yet."""


class JournalEntryNotFoundError(ValueError):
    """Raised when a requested journal entry does not exist."""


class JournalInvalidCursorError(ValueError):
    """Raised when a list cursor is invalid for the current user."""


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
        "reflectionVersion": reflection.reflection_version,
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

        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_count = self.journal_repo.count_entries_since(uid, one_hour_ago)
        if recent_count >= JOURNAL_CREATE_RATE_LIMIT_PER_HOUR:
            raise JournalRateLimitError(
                f"Rate limit exceeded: max {JOURNAL_CREATE_RATE_LIMIT_PER_HOUR} entries per hour"
            )

        if request.client_request_id:
            existing = self.journal_repo.get_entry_by_client_request_id(
                uid, request.client_request_id
            )
            if existing is not None:
                return CreateJournalEntryResponse(
                    entry_id=existing.entry_id,
                    created_at=existing.created_at,
                )

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
            "clientRequestId": request.client_request_id,
            "isDeleted": False,
            "deletedAt": None,
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
            updated_recent = updated_recent[:JOURNAL_RECENT_MAX]

            txn.set(entry_ref, entry_data)
            txn.update(user_ref, {"journalRecent": updated_recent})

        _create_txn(transaction)

        log_analytics_event(
            logger,
            event="journal_created",
            uid=uid,
            entry_type=request.entry_type.value,
            sport=request.sport.value if request.sport else None,
            match_id=request.match_id,
        )

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
            raise JournalEntryNotFoundError(f"Journal entry {entry_id!r} not found")

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
        log_analytics_event(
            logger,
            event="journal_updated",
            uid=uid,
            entry_type=entry.entry_type.value,
            sport=entry.sport.value if entry.sport else None,
            match_id=entry.match_id,
        )

    # ===== GET /me/journal =====

    def get_entry(self, uid: str, entry_id: str) -> JournalEntry | None:
        """
        Fetch a single journal entry owned by uid.

        Returns None if the entry does not exist under the user's
        subcollection path (users/{uid}/journalEntries/{entry_id}).
        Cross-user IDs are invisible — they simply return None (→ 404).
        """
        return self.journal_repo.get_entry(uid, entry_id)

    def list_entries(
        self,
        uid: str,
        limit: int = JOURNAL_LIST_DEFAULT_LIMIT,
        cursor: Optional[dict] = None,
        entry_type: str | None = None,
        sport: str | None = None,
        tag: str | None = None,
    ) -> list[JournalEntry]:
        """List journal entries for a user."""
        if entry_type or sport or tag:
            # API contract supports these params; Firestore-level filtering is deferred.
            raise UnsupportedJournalFilterError("filter not supported yet")

        cursor_entry_id = (cursor or {}).get("entryId")
        if cursor_entry_id:
            cursor_entry = self.journal_repo.get_entry(uid, str(cursor_entry_id))
            if cursor_entry is None:
                raise JournalInvalidCursorError("Invalid cursor")
        return self.journal_repo.list_entries(uid, limit=limit, cursor=cursor)

    # ===== GET /me/journal/loggable-matches =====

    def get_loggable_matches(self, uid: str) -> list[LoggableMatch]:
        """
        Return the caller's recent completed matches for the journal picker.

        Reads the completedMatches cache on the user doc (1 read), enriches each
        entry with an ``already_logged`` flag derived from the journalRecent
        cache, and returns them ordered by finished_at DESC.
        """
        profile = self.users_repo.get_private_profile(uid)
        if profile is None:
            raise ValueError("User not found")

        logged_match_ids = {
            summary.match_id for summary in profile.journal_recent if summary.match_id
        }

        loggable = [
            LoggableMatch(
                match_id=m.match_id,
                sport=m.sport,
                finished_at=m.finished_at,
                result=m.result,
                score_text=m.score_text,
                league_id=m.league_id,
                opponent_uid=m.opponent_uid,
                opponent_name=m.opponent_name,
                already_logged=m.match_id in logged_match_ids,
            )
            for m in profile.completed_matches
        ]
        loggable.sort(key=lambda m: m.finished_at, reverse=True)

        log_analytics_event(
            logger,
            event="loggable_matches_read",
            uid=uid,
        )
        return loggable

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

        log_analytics_event(
            logger,
            event="stats_read",
            uid=uid,
        )
        return self.stats_repo.compute_user_stats(profile)

    def delete_entry(self, uid: str, entry_id: str) -> None:
        """Soft-delete a journal entry and remove it from journalRecent cache."""
        entry = self.journal_repo.get_entry(uid, entry_id, include_deleted=True)
        if entry is None:
            raise JournalEntryNotFoundError(f"Journal entry {entry_id!r} not found")
        if entry.is_deleted:
            return

        now = datetime.now(timezone.utc)
        user_ref = self.client.collection("users").document(uid)
        entry_ref = user_ref.collection("journalEntries").document(entry_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def _delete_txn(txn):
            snap = user_ref.get(transaction=txn)
            current_recent = (snap.to_dict() or {}).get("journalRecent", []) or []
            updated_recent = [s for s in current_recent if s.get("entryId") != entry_id]

            txn.update(entry_ref, {"isDeleted": True, "deletedAt": now})
            txn.update(user_ref, {"journalRecent": updated_recent})

        _delete_txn(transaction)

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
