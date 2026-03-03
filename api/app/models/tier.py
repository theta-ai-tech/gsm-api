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

    def get_threshold(self, tier: TierEnum | str) -> TierThreshold:
        normalized_tier = TierEnum(tier)
        for threshold in self.thresholds:
            if threshold.tier == normalized_tier:
                return threshold

        msg = f"tier {normalized_tier!s} is not configured"
        raise ValueError(msg)

    def get_floor(self, tier: TierEnum | str) -> int:
        return self.get_threshold(tier).min_pts
