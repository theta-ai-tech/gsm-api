from datetime import datetime
from typing import Any

from app.constants import DIVISION_TARGET_SIZE
from app.models.base import GsmBaseModel
from app.models.enums import (
    LeagueFormatEnum,
    LeagueMemberStatusEnum,
    LeagueRoleEnum,
    LeagueStatusEnum,
    LeagueTeamStatusEnum,
    SportEnum,
)


class DivisionConfig(GsmBaseModel):
    target_size: int = DIVISION_TARGET_SIZE
    max_divisions: int | None = None


class RatingRange(GsmBaseModel):
    min: int
    max: int


class Division(GsmBaseModel):
    division_id: str
    name: str
    ordinal: int
    rating_range: RatingRange
    current_players: int
    status: LeagueStatusEnum


class League(GsmBaseModel):
    league_id: str
    name: str
    sport: SportEnum
    season: str | None = None
    status: LeagueStatusEnum
    owner_uid: str
    format: LeagueFormatEnum = LeagueFormatEnum.SINGLES
    region: str | None = None
    max_players: int | None = None
    current_players: int | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    divided_at: datetime | None = None
    tier: str | None = None
    division_config: DivisionConfig | None = None
    meta: dict[str, Any] | None = None


class LeagueMember(GsmBaseModel):
    uid: str
    role: LeagueRoleEnum
    status: LeagueMemberStatusEnum
    joined_at: datetime
    stats: dict[str, Any] | None = None
    display_name: str | None = None
    division_id: str | None = None
    team_id: str | None = None
    partner_uid: str | None = None


class LeagueTeamPartnerInvite(GsmBaseModel):
    """Public view of an unregistered partner slot on a team.

    Email is the durable match key but is intentionally NOT exposed here — only
    the display name and optional phone ever leave the server.
    """

    name: str
    phone: str | None = None


class LeagueTeam(GsmBaseModel):
    team_id: str
    status: LeagueTeamStatusEnum
    captain_uid: str
    partner_uid: str | None = None
    member_uids: list[str]
    name: str
    created_at: datetime
    accepted_at: datetime | None = None
    rating_avg: int | None = None
    division_id: str | None = None
    partner_placeholder_uid: str | None = None
    partner_invite: LeagueTeamPartnerInvite | None = None


class LeagueBrowseCard(GsmBaseModel):
    league_id: str
    name: str
    sport: SportEnum
    status: LeagueStatusEnum
    format: LeagueFormatEnum = LeagueFormatEnum.SINGLES
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
    team_id: str | None = None
    member_uids: list[str] | None = None
