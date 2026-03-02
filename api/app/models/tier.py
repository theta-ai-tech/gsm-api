from datetime import datetime

from pydantic import Field

from app.models.base import GsmBaseModel
from app.models.enums import TierEnum


class TierThreshold(GsmBaseModel):
    tier: TierEnum
    min_pts: int = Field(alias="minPts")
    max_pts: int | None = Field(alias="maxPts")
    label: str
    color: str


class TierConfig(GsmBaseModel):
    thresholds: list[TierThreshold]
    version: int
    updated_at: datetime = Field(alias="updatedAt")
