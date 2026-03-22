from datetime import datetime

from app.models.base import GsmBaseModel
from app.models.enums import SportEnum, TierEnum


class LeaderboardEntry(GsmBaseModel):
    uid: str
    name: str
    pts: int
    tier: TierEnum | None = None
    rank: int
    delta7d: int = 0


class RisingStarEntry(GsmBaseModel):
    uid: str
    name: str
    pts: int
    delta7d: int = 0
    rank: int


class LeaderboardSnapshot(GsmBaseModel):
    region: str
    sport: SportEnum
    entries: list[LeaderboardEntry] = []
    rising_stars: list[RisingStarEntry] = []
    last_updated: datetime | None = None
