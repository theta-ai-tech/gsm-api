import logging
from datetime import datetime

from pydantic import Field, model_validator

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
    went_well: list[str] = []  # skill tags e.g. ["first_serve", "net_play"]
    went_wrong: list[str] = []  # skill tags e.g. ["double_faults", "backhand"]
    opponent_weak: list[str] = []  # opponent weakness tags
    opponent_strong: list[str] = []  # opponent strength tags
    ai_summary: str | None = None  # future AI-generated summary


class JournalEntry(GsmBaseModel):
    entry_id: str
    uid: str  # owner
    created_at: datetime
    title: str
    body: str
    tags: list[str] = []
    match_id: str | None = None
    sport: SportEnum | None = None
    visibility: JournalVisibilityEnum
    entry_type: JournalEntryTypeEnum = JournalEntryTypeEnum.MATCH
    duration_minutes: int | None = None  # training duration
    training_focus: list[TrainingFocusEnum] = []  # training pills
    reflection: MatchReflection | None = None  # post-match review data
    score_text: str | None = None  # denormalized "6-4 7-5"
    result: MatchResultEnum | None = None  # W/L from match


class CreateJournalEntryRequest(GsmBaseModel):
    entry_type: JournalEntryTypeEnum
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default=[], max_length=20)
    match_id: str | None = None  # selected from completedMatches[] cache
    sport: SportEnum | None = None
    score_text: str | None = None  # "6-4 7-5" from match picker or manual
    result: MatchResultEnum | None = None
    duration_minutes: int | None = None
    training_focus: list[TrainingFocusEnum] = []
    visibility: JournalVisibilityEnum = JournalVisibilityEnum.PRIVATE

    @model_validator(mode="after")
    def _validate_entry_type_fields(self) -> "CreateJournalEntryRequest":
        if self.entry_type == JournalEntryTypeEnum.MATCH and self.match_id is None:
            logger.warning(
                "CreateJournalEntryRequest: entry_type=MATCH but match_id not provided"
            )
        if self.entry_type == JournalEntryTypeEnum.TRAINING:
            if self.duration_minutes is None or self.duration_minutes <= 0:
                raise ValueError("duration_minutes must be > 0 for training entries")
        return self


class CreateJournalEntryResponse(GsmBaseModel):
    entry_id: str
    created_at: datetime


class UpdateJournalEntryRequest(GsmBaseModel):
    reflection: MatchReflection | None = None
    tags: list[str] | None = Field(default=None, max_length=20)  # append/replace tags
    body: str | None = Field(default=None, max_length=5000)  # optional notes update
