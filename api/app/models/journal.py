import logging
from datetime import datetime

from pydantic import Field, model_validator

from app.constants import (
    JOURNAL_BODY_MAX,
    JOURNAL_CLIENT_REQUEST_ID_MAX,
    JOURNAL_TAGS_MAX,
    JOURNAL_TITLE_MAX,
)
from app.models.base import GsmBaseModel
from app.models.enums import (
    JournalEntryTypeEnum,
    JournalVisibilityEnum,
    MatchResultEnum,
    SportEnum,
    TrainingFocusEnum,
)

logger = logging.getLogger(__name__)


class MatchReflection(GsmBaseModel):
    went_well: list[str] = Field(
        default_factory=list
    )  # skill tags e.g. ["first_serve", "net_play"]
    went_wrong: list[str] = Field(
        default_factory=list
    )  # skill tags e.g. ["double_faults", "backhand"]
    opponent_weak: list[str] = Field(default_factory=list)  # opponent weakness tags
    opponent_strong: list[str] = Field(default_factory=list)  # opponent strength tags
    ai_summary: str | None = None  # future AI-generated summary
    reflection_version: str | None = None  # taxonomy version, e.g. "v1"


class JournalEntry(GsmBaseModel):
    entry_id: str
    uid: str  # owner
    created_at: datetime
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)
    match_id: str | None = None
    sport: SportEnum | None = None
    visibility: JournalVisibilityEnum
    entry_type: JournalEntryTypeEnum = JournalEntryTypeEnum.MATCH
    duration_minutes: int | None = None  # training duration
    training_focus: list[TrainingFocusEnum] = Field(default_factory=list)  # training pills
    reflection: MatchReflection | None = None  # post-match review data
    score_text: str | None = None  # denormalized "6-4 7-5"
    result: MatchResultEnum | None = None  # W/L from match
    client_request_id: str | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None


class LoggableMatch(GsmBaseModel):
    """A recent completed match offered to the journal match picker."""

    match_id: str
    sport: SportEnum
    finished_at: datetime
    result: MatchResultEnum | None = None
    score_text: str | None = None
    league_id: str | None = None
    opponent_uid: str | None = None
    opponent_name: str | None = None
    already_logged: bool = False


class CreateJournalEntryRequest(GsmBaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "entry_type": "match",
                "title": "Quarter-final win",
                "body": "Stayed aggressive on second serve. Net approach worked well.",
                "match_id": "match_abc123",
                "sport": "tennis",
                "score_text": "6-4 7-5",
                "result": "W",
                "visibility": "private",
                "tags": ["tournament", "grass"],
            }
        }
    }

    entry_type: JournalEntryTypeEnum
    title: str = Field(default="", max_length=JOURNAL_TITLE_MAX)
    body: str = Field(default="", max_length=JOURNAL_BODY_MAX)
    tags: list[str] = Field(default_factory=list, max_length=JOURNAL_TAGS_MAX)
    match_id: str | None = None  # selected from completedMatches[] cache
    sport: SportEnum | None = None
    score_text: str | None = None  # "6-4 7-5" from match picker or manual
    result: MatchResultEnum | None = None
    duration_minutes: int | None = None
    training_focus: list[TrainingFocusEnum] = Field(default_factory=list)
    visibility: JournalVisibilityEnum = JournalVisibilityEnum.PRIVATE
    client_request_id: str | None = Field(default=None, max_length=JOURNAL_CLIENT_REQUEST_ID_MAX)

    @model_validator(mode="after")
    def _validate_entry_type_fields(self) -> "CreateJournalEntryRequest":
        if self.entry_type == JournalEntryTypeEnum.MATCH and self.match_id is None:
            logger.warning("CreateJournalEntryRequest: entry_type=MATCH but match_id not provided")
        if self.entry_type == JournalEntryTypeEnum.TRAINING:
            if self.duration_minutes is None or self.duration_minutes <= 0:
                raise ValueError("duration_minutes must be > 0 for training entries")
        return self


class CreateJournalEntryResponse(GsmBaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "entry_id": "entry_xyz789",
                "created_at": "2026-02-25T10:30:00Z",
            }
        }
    }

    entry_id: str
    created_at: datetime


class UpdateJournalEntryRequest(GsmBaseModel):
    reflection: MatchReflection | None = None
    tags: list[str] | None = Field(default=None, max_length=JOURNAL_TAGS_MAX)  # append/replace tags
    body: str | None = Field(default=None, max_length=JOURNAL_BODY_MAX)  # optional notes update
