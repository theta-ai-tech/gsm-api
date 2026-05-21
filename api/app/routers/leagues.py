from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies.repos import get_league_service, get_leagues_repo
from app.deps import get_current_user, get_role_service
from app.models.base import GsmBaseModel
from app.models.enums import LeagueStatusEnum, SportEnum
from app.models.league import League, LeagueBrowseCard, StandingsEntry
from app.repos.leagues_repo import LeaguesRepo
from app.security import CurrentUser, require_league_member, require_membership
from app.services.league_service import LeagueService
from app.services.role_service import RoleService

router = APIRouter(prefix="/leagues", tags=["leagues"])


class LeagueBrowseResponse(GsmBaseModel):
    leagues: list[LeagueBrowseCard]
    next_cursor: str | None = None


class StandingsResponse(GsmBaseModel):
    league_id: str
    standings: list[StandingsEntry]


def _league_to_browse_card(league: League) -> LeagueBrowseCard:
    return LeagueBrowseCard(
        league_id=league.league_id,
        name=league.name,
        sport=league.sport,
        status=league.status,
        region=league.region,
        tier=league.tier,
        max_players=league.max_players,
        current_players=league.current_players,
        start_date=league.start_date,
    )


def _encode_cursor(league: League) -> str | None:
    if league.start_date is None:
        return None
    payload = {
        "startDate": league.start_date.isoformat(),
        "leagueId": league.league_id,
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(cursor_str: str) -> dict:
    try:
        data = json.loads(base64.b64decode(cursor_str))
        start_date_str = data.get("startDate")
        return {
            "startDate": datetime.fromisoformat(start_date_str) if start_date_str else None,
            "leagueId": data.get("leagueId"),
        }
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")


@router.get("", response_model=LeagueBrowseResponse)
def list_leagues(
    region: Optional[str] = Query(default=None),
    sport: Optional[SportEnum] = Query(default=None),
    league_status: Optional[LeagueStatusEnum] = Query(
        default=LeagueStatusEnum.OPEN, alias="status"
    ),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    leagues_repo: LeaguesRepo = Depends(get_leagues_repo),
) -> LeagueBrowseResponse:
    cursor_dict = _decode_cursor(cursor) if cursor else None
    results = leagues_repo.list_by_filter(
        region=region,
        sport=sport,
        status=league_status,
        limit=limit + 1,
        cursor=cursor_dict,
    )
    has_more = len(results) > limit
    page = results[:limit]
    next_cursor = _encode_cursor(page[-1]) if has_more and page else None
    return LeagueBrowseResponse(
        leagues=[_league_to_browse_card(lg) for lg in page],
        next_cursor=next_cursor,
    )


@router.post(
    "/{league_id}/members",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_league_member(required_role="admin"))],
)
def add_league_member(league_id: str) -> dict:
    # TODO(LG-future): wire to LeagueMemberRepo.add_member() once implemented
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")


@router.delete(
    "/{league_id}/members/{uid}",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_league_member(required_role="admin"))],
)
def remove_league_member(league_id: str, uid: str) -> None:
    # TODO(LG-future): wire to LeagueMemberRepo.remove_member() once implemented
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")


def _require_league_member_or_404(
    league_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    leagues_repo: LeaguesRepo = Depends(get_leagues_repo),
    role_service: RoleService = Depends(get_role_service),
) -> None:
    if leagues_repo.get_by_id(league_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    require_membership(current_user=current_user, league_id=league_id, role_service=role_service)


@router.get("/{league_id}/standings", response_model=StandingsResponse)
def get_league_standings(
    league_id: str,
    _auth: None = Depends(_require_league_member_or_404),
    league_service: LeagueService = Depends(get_league_service),
) -> StandingsResponse:
    standings = league_service.get_standings(league_id)
    return StandingsResponse(league_id=league_id, standings=standings)


@router.get("/{league_id}", response_model=League)
def get_league(
    league_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    leagues_repo: LeaguesRepo = Depends(get_leagues_repo),
) -> League:
    league = leagues_repo.get_by_id(league_id)
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    return league
