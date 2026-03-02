from datetime import datetime

from app.models.base import GsmBaseModel
from app.models.enums import (
    JournalEntryTypeEnum,
    LeagueRoleEnum,
    LeagueStatusEnum,
    LevelEnum,
    MatchResultEnum,
    SportEnum,
    TierEnum,
)


class SportRanking(GsmBaseModel):
    sport: SportEnum
    pts: int
    global_ranking: int | None = None
    tier: TierEnum | None = None
    registration_tier: TierEnum | None = None
    last_updated: datetime | None = None


class PerSportRankings(GsmBaseModel):
    tennis: SportRanking | None = None
    padel: SportRanking | None = None
    pickleball: SportRanking | None = None


class PerSportLevels(GsmBaseModel):
    tennis: LevelEnum | None = None
    padel: LevelEnum | None = None
    pickleball: LevelEnum | None = None


class UserPreferences(GsmBaseModel):
    area: int
    comment: str = "integer key referencing a separate region config; may evolve to ISO code later."
    levels: PerSportLevels
    sports: list[SportEnum]


class SetScore(GsmBaseModel):
    p1_games: int
    p2_games: int
    tiebreak_score: str | None = None

    def model_post_init(self, _context) -> None:
        if self.p1_games < 0 or self.p2_games < 0:
            msg = "p1_games and p2_games must be non-negative"
            raise ValueError(msg)


class MatchScore(GsmBaseModel):
    """Structured score; free-text like '6-4 6-3' can be derived from this."""

    sets: list[SetScore]
    winner_uid: str | None = None
    retired: bool = False


class LeagueSummary(GsmBaseModel):
    league_id: str
    name: str
    sport: SportEnum
    status: LeagueStatusEnum
    role: LeagueRoleEnum | None = None


class MatchOpponentSummary(GsmBaseModel):
    uid: str
    name: str | None = None


class UserMatchSummary(GsmBaseModel):
    match_id: str
    sport: SportEnum
    scheduled_at: datetime
    league_id: str | None = None
    court_id: str | None = None
    opponents: list[MatchOpponentSummary]


class UserCompletedMatchSummary(GsmBaseModel):
    match_id: str
    sport: SportEnum
    finished_at: datetime
    result: MatchResultEnum | None = None
    score_text: str | None = None
    league_id: str | None = None


class JournalEntrySummary(GsmBaseModel):
    entry_id: str
    created_at: datetime
    title: str
    match_id: str | None = None
    sport: SportEnum | None = None
    entry_type: JournalEntryTypeEnum | None = None


class CursorBundle(GsmBaseModel):
    upcoming_matches: str | None = None
    completed_matches: str | None = None
    journal: str | None = None
