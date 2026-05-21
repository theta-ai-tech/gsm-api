from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies.repos import get_leagues_repo, get_matches_repo
from app.deps import get_current_user, get_role_service
from app.models.base import GsmBaseModel
from app.models.enums import LeagueStatusEnum, SportEnum
from app.models.league import League, LeagueBrowseCard
from app.models.match import Match
from app.repos.leagues_repo import LeaguesRepo
from app.repos.matches_repo import MatchesRepo
from app.security import CurrentUser, require_membership
from app.services.role_service import RoleService

router = APIRouter(prefix="/leagues", tags=["leagues"])


class LeagueBrowseResponse(GsmBaseModel):
    leagues: list[LeagueBrowseCard]
    next_cursor: str | None = None


class LeagueMatchesResponse(GsmBaseModel):
    matches: list[Match]
    next_cursor: str | None = None


# --- League browse cursor helpers ---


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


# --- Match cursor helpers ---


def _encode_match_cursor(match: Match, match_type: str) -> str | None:
    if match_type == "upcoming":
        if match.scheduled_at is None:
            return None
        payload = {"scheduledAt": match.scheduled_at.isoformat(), "matchId": match.match_id}
    else:
        if match.finished_at is None:
            return None
        payload = {"finishedAt": match.finished_at.isoformat(), "matchId": match.match_id}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _decode_match_cursor(cursor_str: str, match_type: str) -> dict:
    try:
        data = json.loads(base64.b64decode(cursor_str))
        if match_type == "upcoming":
            ts_str = data.get("scheduledAt")
            return {
                "scheduledAt": datetime.fromisoformat(ts_str) if ts_str else None,
                "matchId": data.get("matchId"),
            }
        else:
            ts_str = data.get("finishedAt")
            return {
                "finishedAt": datetime.fromisoformat(ts_str) if ts_str else None,
                "matchId": data.get("matchId"),
            }
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")


# --- Auth dependency ---


def _require_league_member_or_404(
    league_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    leagues_repo: LeaguesRepo = Depends(get_leagues_repo),
    role_service: RoleService = Depends(get_role_service),
) -> None:
    if leagues_repo.get_by_id(league_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    require_membership(current_user=current_user, league_id=league_id, role_service=role_service)


# --- Endpoints ---


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


@router.get("/{league_id}/matches", response_model=LeagueMatchesResponse)
def get_league_matches(
    league_id: str,
    match_type: Literal["upcoming", "completed"] = Query(default="upcoming", alias="type"),
    limit: int = Query(default=10, ge=1, le=50),
    cursor: Optional[str] = Query(default=None),
    _auth: None = Depends(_require_league_member_or_404),
    matches_repo: MatchesRepo = Depends(get_matches_repo),
) -> LeagueMatchesResponse:
    cursor_dict = _decode_match_cursor(cursor, match_type) if cursor else None
    if match_type == "upcoming":
        results = matches_repo.list_upcoming_for_league(
            league_id, limit=limit + 1, cursor=cursor_dict
        )
    else:
        results = matches_repo.list_completed_for_league(
            league_id, limit=limit + 1, cursor=cursor_dict
        )
    has_more = len(results) > limit
    page = results[:limit]
    next_cursor = _encode_match_cursor(page[-1], match_type) if has_more and page else None
    return LeagueMatchesResponse(matches=page, next_cursor=next_cursor)


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
