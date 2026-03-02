from datetime import datetime


from app.models.base import GsmBaseModel
from app.models.enums import PointHistoryReasonEnum, SportEnum, TierEnum


class PointHistoryEntry(GsmBaseModel):
    entry_id: str
    sport: SportEnum
    pts: int
    delta: int
    reason: PointHistoryReasonEnum
    match_id: str | None = None
    opponent_uid: str | None = None
    opponent_pts_before: int | None = None
    league_id: str | None = None
    created_at: datetime
    tier_before: TierEnum | None = None
    tier_after: TierEnum | None = None


__all__ = ["PointHistoryEntry"]
