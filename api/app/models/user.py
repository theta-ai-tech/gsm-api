from pydantic import EmailStr, HttpUrl

from app.models.base import GsmBaseModel
from app.models.common import (
    CursorBundle,
    JournalEntrySummary,
    LeagueSummary,
    PerSportRankings,
    UserCompletedMatchSummary,
    UserMatchSummary,
    UserPreferences,
)
from app.models.skill_dna import SportSkillDna
from app.models.stats import NorthStarGoal


class PublicUserProfile(GsmBaseModel):
    """Public view of a user suitable for opponent/profile screens. No email/phone/preferences."""

    uid: str
    name: str
    profile_url: HttpUrl | None = None
    rankings: PerSportRankings
    leagues_active: list[LeagueSummary] = []
    leagues_completed: list[LeagueSummary] = []
    skill_dna: dict[str, SportSkillDna] | None = None
    is_pro: bool = False


class PrivateUserProfile(PublicUserProfile):
    """Private view for the authenticated user (“Me” tab). Only returned when requester.uid == profile.uid."""

    email: EmailStr
    phone: str | None = None
    preferences: UserPreferences
    upcoming_matches: list[UserMatchSummary] = []
    completed_matches: list[UserCompletedMatchSummary] = []
    journal_recent: list[JournalEntrySummary] = []
    cursors: CursorBundle | None = None
    north_star_goal: NorthStarGoal | None = None
