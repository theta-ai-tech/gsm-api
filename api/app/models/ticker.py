from datetime import datetime

from app.models.base import GsmBaseModel
from app.models.enums import SportEnum, TierEnum, TickerEventTypeEnum


class TickerEvent(GsmBaseModel):
    event_id: str = ""
    type: TickerEventTypeEnum
    sport: SportEnum
    region: str
    created_at: datetime
    expires_at: datetime

    # upset-specific fields
    winner_uid: str | None = None
    winner_name: str | None = None
    loser_tier: TierEnum | None = None
    delta: int = 0

    # shared subject fields (personal_best, win_streak, tier_crossed)
    user_uid: str | None = None
    user_name: str | None = None

    # personal_best fields
    new_pts: int | None = None
    previous_best: int | None = None

    # win_streak fields
    streak: int | None = None

    # tier_crossed fields
    tier_before: TierEnum | None = None
    tier_after: TierEnum | None = None
    direction: str | None = None
