from datetime import datetime

from app.models.base import GsmBaseModel
from app.models.enums import SportEnum, TierEnum, TickerEventTypeEnum


class TickerEvent(GsmBaseModel):
    event_id: str = ""
    type: TickerEventTypeEnum
    sport: SportEnum
    region: str
    winner_uid: str
    winner_name: str
    loser_tier: TierEnum | None = None
    delta: int = 0
    created_at: datetime
    expires_at: datetime
