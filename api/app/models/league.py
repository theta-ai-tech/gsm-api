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
    region: str | None = None
    max_players: int | None = None
    current_players: int | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    tier: str | None = None
    meta: dict[str, Any] | None = None


class LeagueMember(GsmBaseModel):
    uid: str
    role: LeagueRoleEnum
    status: LeagueMemberStatusEnum
    joined_at: datetime
    stats: dict[str, Any] | None = None
    display_name: str | None = None


class LeagueBrowseCard(GsmBaseModel):
    league_id: str
    name: str
    sport: SportEnum
    status: LeagueStatusEnum
    region: str | None = None
    tier: str | None = None
    max_players: int | None = None
    current_players: int | None = None
    start_date: datetime | None = None


class StandingsEntry(GsmBaseModel):
    rank: int
    uid: str
    display_name: str
    wins: int
    losses: int
    tier_ring: str | None = None
