from datetime import datetime

from pydantic import Field

from app.models.base import GsmBaseModel


class SkillAxisData(GsmBaseModel):
    positive: int
    negative: int
    score: int


class SportSkillDna(GsmBaseModel):
    serve: SkillAxisData | None = None
    power: SkillAxisData | None = None
    net_play: SkillAxisData | None = None
    stamina: SkillAxisData | None = None
    mental: SkillAxisData | None = None
    total_reflections: int = Field(default=0, alias="totalReflections")
    last_updated: datetime | None = Field(default=None, alias="lastUpdated")
