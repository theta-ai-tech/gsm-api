from datetime import datetime
from typing import Self

from pydantic import model_validator

from app.models.base import GsmBaseModel
from app.models.enums import SportEnum, TierEnum, TickerEventTypeEnum

_REQUIRED_FIELDS: dict[TickerEventTypeEnum, list[str]] = {
    TickerEventTypeEnum.UPSET: ["winner_uid", "winner_name", "loser_tier"],
    TickerEventTypeEnum.PERSONAL_BEST: ["user_uid", "user_name", "new_pts", "previous_best"],
    TickerEventTypeEnum.WIN_STREAK: ["user_uid", "user_name", "streak"],
    TickerEventTypeEnum.TIER_CROSSED: [
        "user_uid",
        "user_name",
        "tier_before",
        "tier_after",
        "direction",
    ],
}


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

    @model_validator(mode="after")
    def _check_required_per_type(self) -> Self:
        required = _REQUIRED_FIELDS.get(self.type, [])
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"Event type '{self.type}' requires fields: {', '.join(missing)}")
        return self
