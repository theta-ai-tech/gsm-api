from datetime import datetime
from typing import Any

from app.models.base import GsmBaseModel
from app.models.enums import LeagueMemberStatusEnum, LeagueRoleEnum, LeagueStatusEnum, SportEnum


class League(GsmBaseModel):
    league_id: str
    name: str
    sport: SportEnum
    season: str | None = None
    status: LeagueStatusEnum
    owner_uid: str
    meta: dict[str, Any] | None = None


class LeagueMember(GsmBaseModel):
    uid: str
    role: LeagueRoleEnum
    status: LeagueMemberStatusEnum
    joined_at: datetime
    stats: dict[str, Any] | None = None
