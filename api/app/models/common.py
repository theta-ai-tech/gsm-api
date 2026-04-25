from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

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


class GeoCoordinates(GsmBaseModel):
    """Latitude/longitude pair used by VenueRef and other geo-tagged models."""

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class VenueRef(GsmBaseModel):
    """Reference to a venue.

    A venue can be either a curated Firestore document (``venue_id``) or a
    Google Places-resolved location (``place_id``). At least one of the two
    identifier fields must be non-null; both may be set when a curated venue
    has been cross-referenced with a Google Place. ``name`` and
    ``coordinates`` are always populated so that clients can render the
    venue without making additional lookups.
    """

    venue_id: str | None = Field(default=None, alias="venueId")
    place_id: str | None = Field(default=None, alias="placeId")
    name: str
    coordinates: GeoCoordinates

    @model_validator(mode="after")
    def _ensure_identifier(self) -> "VenueRef":
        if self.venue_id is None and self.place_id is None:
            msg = "VenueRef requires at least one of venue_id or place_id"
            raise ValueError(msg)
        return self

    @model_validator(mode="before")
    @classmethod
    def _normalize_empty_strings(cls, data: Any) -> Any:
        """Treat empty-string identifiers as ``None`` so Firestore round-trips
        behave the same as explicit nulls."""
        if isinstance(data, dict):
            data = dict(data)
            for snake, camel in (("venue_id", "venueId"), ("place_id", "placeId")):
                if data.get(snake) == "":
                    data[snake] = None
                if data.get(camel) == "":
                    data[camel] = None
        return data


class ParticipantEntry(GsmBaseModel):
    """A single participant in a match or broadcast.

    For singles, ``team`` is ``None``. For doubles, ``team`` is ``'A'`` or
    ``'B'`` to indicate which side the player is on. ``display_name`` is the
    short label shown in UI (typically first name + last initial).
    """

    uid: str = Field(min_length=1)
    team: str | None = Field(default=None)
    display_name: str = Field(min_length=1, alias="displayName")

    @model_validator(mode="after")
    def _validate_team(self) -> "ParticipantEntry":
        if self.team is not None and self.team not in {"A", "B"}:
            msg = "team must be 'A', 'B', or None"
            raise ValueError(msg)
        return self


class SportRanking(GsmBaseModel):
    sport: SportEnum
    pts: int
    global_ranking: int | None = None
    tier: TierEnum | None = None
    registration_tier: TierEnum | None = None
    last_updated: datetime | None = None
    personal_best: int | None = None
    current_streak: int = 0
    best_streak: int = 0


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
    feed_opt_out: bool = False


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
