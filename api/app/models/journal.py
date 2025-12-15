from datetime import datetime

from app.models.base import GsmBaseModel
from app.models.enums import JournalVisibilityEnum, SportEnum


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
