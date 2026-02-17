from datetime import datetime

from app.models.base import GsmBaseModel
from app.models.enums import (
    JournalEntryTypeEnum,
    JournalVisibilityEnum,
    MatchResultEnum,
    SportEnum,
    TrainingFocusEnum,
)


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
