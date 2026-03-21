from datetime import datetime

from app.models.base import GsmBaseModel


class ScoutingTagCount(GsmBaseModel):
    count: int = 0
    last_reported: datetime | None = None


class ScoutingSportData(GsmBaseModel):
    weak: dict[str, ScoutingTagCount] = {}
    strong: dict[str, ScoutingTagCount] = {}
    total_reports: int = 0
    unique_reporters: int = 0
    last_updated: datetime | None = None


class ScoutingProfile(GsmBaseModel):
    uid: str
    tennis: ScoutingSportData | None = None
    padel: ScoutingSportData | None = None
    pickleball: ScoutingSportData | None = None
