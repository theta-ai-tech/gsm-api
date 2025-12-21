"""
Query contract stubs for Firestore access. C3.1 defines the shapes; C3.2 will implement them.
"""

from typing import List, Optional

from app.models import (
    JournalEntry,
    PrivateUserProfile,
    PublicUserProfile,
    Match,
)


def get_user_profile(uid: str, requester_uid: str) -> PublicUserProfile | PrivateUserProfile:
    """Fetch user profile; return private view only if requester_uid == uid."""
    raise NotImplementedError


def list_upcoming_matches_for_user(
    uid: str, limit: int, cursor: Optional[str] = None
) -> List[Match]:
    """List upcoming matches for a user, ordered by scheduledAt ASC."""
    raise NotImplementedError


def list_completed_matches_for_user(
    uid: str, limit: int, cursor: Optional[str] = None
) -> List[Match]:
    """List completed matches for a user, ordered by finishedAt DESC."""
    raise NotImplementedError


def list_matches_by_league(
    league_id: str, status: str, limit: int, cursor: Optional[str] = None
) -> List[Match]:
    """List league matches, filtered by status (scheduled/completed) with appropriate ordering."""
    raise NotImplementedError


def list_journal_entries_for_user(
    uid: str, limit: int, cursor: Optional[str] = None
) -> List[JournalEntry]:
    """List journal entries for a user, ordered by createdAt DESC."""
    raise NotImplementedError
