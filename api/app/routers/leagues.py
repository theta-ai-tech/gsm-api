from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies.repos import (
    get_divisions_repo,
    get_league_service,
    get_leagues_repo,
    get_matches_repo,
)
from app.deps import get_current_user, get_role_service
from app.models.base import GsmBaseModel
from app.models.enums import LeagueFormatEnum, LeagueStatusEnum, LeagueTeamStatusEnum, SportEnum
from app.models.league import (
    Division,
    League,
    LeagueBrowseCard,
    LeagueMember,
    LeagueTeam,
    StandingsEntry,
)
from app.models.match import Match
from app.repos.divisions_repo import DivisionsRepo
from app.repos.leagues_repo import LeaguesRepo
from app.repos.matches_repo import MatchesRepo
from app.security import CurrentUser, require_league_member, require_membership
from app.services.league_service import (
    LeagueKickoffConflictError,
    LeagueKickoffNotFoundError,
    LeagueKickoffResult,
    LeagueService,
    LeagueTeamConflictError,
    LeagueTeamError,
    LeagueTeamForbiddenError,
    LeagueTeamNotFoundError,
    LeagueTeamValidationError,
)
from app.services.role_service import RoleService

router = APIRouter(prefix="/leagues", tags=["leagues"])


class LeagueBrowseResponse(GsmBaseModel):
    leagues: list[LeagueBrowseCard]
    next_cursor: str | None = None


class LeagueJoinRequest(GsmBaseModel):
    partner_uid: str | None = None


class LeagueTeamsResponse(GsmBaseModel):
    league_id: str
    teams: list[LeagueTeam]


class LeagueMatchesResponse(GsmBaseModel):
    matches: list[Match]
    next_cursor: str | None = None


class StandingsResponse(GsmBaseModel):
    league_id: str
    standings: list[StandingsEntry]


class KickoffLeagueResponse(GsmBaseModel):
    league_id: str
    division_count: int
    division_ids: list[str]
    divisions: list[Division]
    already_kicked_off: bool = False


class DivisionsResponse(GsmBaseModel):
    league_id: str
    divisions: list[Division]


def _league_to_browse_card(league: League) -> LeagueBrowseCard:
    return LeagueBrowseCard(
        league_id=league.league_id,
        name=league.name,
        sport=league.sport,
        status=league.status,
        format=league.format,
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


def _get_divided_league_or_409(league_id: str, leagues_repo: LeaguesRepo) -> League:
    league = leagues_repo.get_by_id(league_id)
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    if league.status != LeagueStatusEnum.ACTIVE or league.divided_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="league not yet divided")
    return league


def _get_existing_division_or_404(
    league_id: str, division_id: str, divisions_repo: DivisionsRepo
) -> Division:
    division = divisions_repo.get_by_id(league_id, division_id)
    if division is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Division not found")
    return division


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


def _map_team_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LeagueTeamNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, LeagueTeamValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, LeagueTeamForbiddenError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, LeagueTeamConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    error_msg = str(exc)
    if "not found" in error_msg:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)


@router.post(
    "/{league_id}/join",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
)
def join_league(
    league_id: str,
    body: LeagueJoinRequest | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    leagues_repo: LeaguesRepo = Depends(get_leagues_repo),
    league_service: LeagueService = Depends(get_league_service),
) -> LeagueMember | LeagueTeam:
    partner_uid = body.partner_uid if body is not None else None

    league = leagues_repo.get_by_id(league_id)
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")

    if league.format == LeagueFormatEnum.DOUBLES:
        if not partner_uid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This doubles league requires a partner_uid",
            )
        try:
            return league_service.invite_team(
                league_id, current_user.uid, partner_uid, current_user.display_name
            )
        except LeagueTeamError as e:
            raise _map_team_error(e)

    if partner_uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This singles league does not accept a partner_uid",
        )
    try:
        return league_service.join_league(league_id, current_user.uid, current_user.display_name)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)


@router.post("/{league_id}/teams/{team_id}/accept", response_model=LeagueTeam)
def accept_team(
    league_id: str,
    team_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    league_service: LeagueService = Depends(get_league_service),
) -> LeagueTeam:
    try:
        return league_service.accept_team(league_id, team_id, current_user.uid)
    except LeagueTeamError as e:
        raise _map_team_error(e)


@router.post("/{league_id}/teams/{team_id}/decline", response_model=LeagueTeam)
def decline_team(
    league_id: str,
    team_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    league_service: LeagueService = Depends(get_league_service),
) -> LeagueTeam:
    try:
        return league_service.decline_team(league_id, team_id, current_user.uid)
    except LeagueTeamError as e:
        raise _map_team_error(e)


@router.delete("/{league_id}/teams/{team_id}", response_model=LeagueTeam)
def cancel_team(
    league_id: str,
    team_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    league_service: LeagueService = Depends(get_league_service),
) -> LeagueTeam:
    try:
        return league_service.cancel_team(league_id, team_id, current_user.uid)
    except LeagueTeamError as e:
        raise _map_team_error(e)


@router.get("/{league_id}/teams", response_model=LeagueTeamsResponse)
def list_league_teams(
    league_id: str,
    team_status: Optional[LeagueTeamStatusEnum] = Query(default=None, alias="status"),
    mine: bool = Query(default=False),
    current_user: CurrentUser = Depends(get_current_user),
    leagues_repo: LeaguesRepo = Depends(get_leagues_repo),
    role_service: RoleService = Depends(get_role_service),
) -> LeagueTeamsResponse:
    if leagues_repo.get_by_id(league_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")

    if mine:
        # Default to actionable teams only — declined/cancelled invites are
        # noise for the "outstanding invites on launch" use case.
        statuses = (
            [team_status]
            if team_status is not None
            else [LeagueTeamStatusEnum.PENDING, LeagueTeamStatusEnum.ACTIVE]
        )
        teams = leagues_repo.find_teams_for_user(league_id, current_user.uid, statuses)
    else:
        require_membership(
            current_user=current_user, league_id=league_id, role_service=role_service
        )
        teams = leagues_repo.list_teams(league_id, status=team_status)
    return LeagueTeamsResponse(league_id=league_id, teams=teams)


def _kickoff_result_to_response(result: LeagueKickoffResult) -> KickoffLeagueResponse:
    return KickoffLeagueResponse(
        league_id=result.league_id,
        division_count=len(result.divisions),
        division_ids=[division.division_id for division in result.divisions],
        divisions=result.divisions,
        already_kicked_off=result.already_kicked_off,
    )


@router.post(
    "/{league_id}/kickoff",
    response_model=KickoffLeagueResponse,
    dependencies=[Depends(require_league_member(required_role="admin"))],
)
def kickoff_league(
    league_id: str,
    league_service: LeagueService = Depends(get_league_service),
) -> KickoffLeagueResponse:
    try:
        return _kickoff_result_to_response(league_service.kickoff_league(league_id))
    except LeagueKickoffNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except LeagueKickoffConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


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


@router.get("/{league_id}/standings", response_model=StandingsResponse)
def get_league_standings(
    league_id: str,
    _auth: None = Depends(_require_league_member_or_404),
    league_service: LeagueService = Depends(get_league_service),
) -> StandingsResponse:
    standings = league_service.get_standings(league_id)
    return StandingsResponse(league_id=league_id, standings=standings)


@router.get("/{league_id}/divisions", response_model=DivisionsResponse)
def list_league_divisions(
    league_id: str,
    _auth: None = Depends(_require_league_member_or_404),
    leagues_repo: LeaguesRepo = Depends(get_leagues_repo),
    divisions_repo: DivisionsRepo = Depends(get_divisions_repo),
) -> DivisionsResponse:
    _get_divided_league_or_409(league_id, leagues_repo)
    divisions = divisions_repo.list_for_league(league_id)
    if not divisions:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="league not yet divided")
    return DivisionsResponse(league_id=league_id, divisions=divisions)


@router.get(
    "/{league_id}/divisions/{division_id}/standings",
    response_model=StandingsResponse,
)
def get_division_standings(
    league_id: str,
    division_id: str,
    _auth: None = Depends(_require_league_member_or_404),
    leagues_repo: LeaguesRepo = Depends(get_leagues_repo),
    divisions_repo: DivisionsRepo = Depends(get_divisions_repo),
    league_service: LeagueService = Depends(get_league_service),
) -> StandingsResponse:
    _get_divided_league_or_409(league_id, leagues_repo)
    _get_existing_division_or_404(league_id, division_id, divisions_repo)
    standings = league_service.get_division_standings(league_id, division_id)
    return StandingsResponse(league_id=league_id, standings=standings)


@router.get(
    "/{league_id}/divisions/{division_id}/matches",
    response_model=LeagueMatchesResponse,
)
def get_division_matches(
    league_id: str,
    division_id: str,
    match_type: Literal["upcoming", "completed"] = Query(default="upcoming", alias="type"),
    limit: int = Query(default=10, ge=1, le=50),
    cursor: Optional[str] = Query(default=None),
    _auth: None = Depends(_require_league_member_or_404),
    leagues_repo: LeaguesRepo = Depends(get_leagues_repo),
    divisions_repo: DivisionsRepo = Depends(get_divisions_repo),
    matches_repo: MatchesRepo = Depends(get_matches_repo),
) -> LeagueMatchesResponse:
    _get_divided_league_or_409(league_id, leagues_repo)
    _get_existing_division_or_404(league_id, division_id, divisions_repo)
    cursor_dict = _decode_match_cursor(cursor, match_type) if cursor else None
    if match_type == "upcoming":
        results = matches_repo.list_upcoming_for_division(
            league_id, division_id, limit=limit + 1, cursor=cursor_dict
        )
    else:
        results = matches_repo.list_completed_for_division(
            league_id, division_id, limit=limit + 1, cursor=cursor_dict
        )
    has_more = len(results) > limit
    page = results[:limit]
    next_cursor = _encode_match_cursor(page[-1], match_type) if has_more and page else None
    return LeagueMatchesResponse(matches=page, next_cursor=next_cursor)


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
