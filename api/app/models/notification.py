from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import model_validator

from app.models.base import GsmBaseModel
from app.models.enums import PlayNotificationIntentTypeEnum

_REQUIRED_FIELDS: dict[PlayNotificationIntentTypeEnum, list[str]] = {
    PlayNotificationIntentTypeEnum.INCOMING_OFFER: ["offer_id"],
    PlayNotificationIntentTypeEnum.MATCH_SCHEDULED: ["match_id"],
    PlayNotificationIntentTypeEnum.SCORE_CONFIRM_REQUIRED: ["match_id"],
}


class PlayNotificationIntent(GsmBaseModel):
    intent_id: str = ""
    type: PlayNotificationIntentTypeEnum
    target_uid: str
    title: str
    body: str
    offer_id: str | None = None
    match_id: str | None = None
    broadcast_id: str | None = None
    dedupe_key: str
    created_at: datetime

    @model_validator(mode="after")
    def _check_required_per_type(self) -> Self:
        required = _REQUIRED_FIELDS.get(self.type, [])
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"Intent type '{self.type}' requires fields: {', '.join(missing)}")
        return self
