from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.dependencies.repos import get_users_repo
from app.deps import get_current_user
from app.models.base import GsmBaseModel
from app.models.enums import SportEnum
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

router = APIRouter(prefix="/players", tags=["players"])


class PlayerSearchResult(GsmBaseModel):
    uid: str
    display_name: str
    profile_url: str | None = None
    pts: int | None = None


class PlayersSearchResponse(GsmBaseModel):
    players: list[PlayerSearchResult]


def _resolve_pts(doc: dict, sport: SportEnum) -> int | None:
    rankings = doc.get("rankings") or {}
    sport_ranking = rankings.get(sport.value) or {}
    pts = sport_ranking.get("pts")
    return int(pts) if pts is not None else None


@router.get("", response_model=PlayersSearchResponse)
def search_players(
    search: str = Query(..., min_length=1),
    sport: Optional[SportEnum] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=20),
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
) -> PlayersSearchResponse:
    docs = users_repo.search_by_name_prefix(query=search, limit=limit, exclude_uid=current_user.uid)
    players = [
        PlayerSearchResult(
            uid=doc.get("uid", ""),
            display_name=doc.get("name", ""),
            profile_url=doc.get("profileUrl"),
            pts=_resolve_pts(doc, sport) if sport is not None else None,
        )
        for doc in docs
    ]
    return PlayersSearchResponse(players=players)
