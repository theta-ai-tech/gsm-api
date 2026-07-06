"""
Tab 4 CLUBHOUSE router - Athlete Card & Resume endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field, field_validator

from app.dependencies.repos import get_region_config_repo, get_users_repo
from app.deps import get_current_user
from app.models.base import GsmBaseModel, HttpUrl
from app.models.common import PerSportLevels
from app.models.enums import SportEnum
from app.models.user import PrivateUserProfile
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.clubhouse_service import (
    build_athlete_card_sports,
    build_profile_update_paths,
    compute_match_totals,
)


# ---------------------------------------------------------------------------
# Response models (endpoint-local, not shared)
# ---------------------------------------------------------------------------


class AthleteCardSport(GsmBaseModel):
    sport: SportEnum
    pts: int
    tier: str | None
    global_ranking: int | None
    personal_best: int | None
    current_streak: int
    best_streak: int


class AthleteResume(GsmBaseModel):
    total_matches: int
    total_wins: int
    leagues_completed: int
    sports: list[AthleteCardSport]


class ClubhouseProfileResponse(GsmBaseModel):
    uid: str
    display_name: str
    avatar_url: str | None
    resume: AthleteResume


# ---------------------------------------------------------------------------
# Request models (endpoint-local, not shared)
# ---------------------------------------------------------------------------


class UpdateClubhouseProfileRequest(GsmBaseModel):
    """Partial update of the caller's own profile.

    Every field is optional; ``None`` means "not provided" (avatar cannot be
    cleared via this endpoint). Unknown top-level fields are rejected with 422
    (``extra="forbid"`` on ``GsmBaseModel``).
    """

    display_name: str | None = Field(default=None, max_length=100)
    avatar_url: HttpUrl | None = None
    area: int | None = None
    levels: PerSportLevels | None = None

    @field_validator("display_name")
    @classmethod
    def _strip_and_require_nonempty(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be empty")
        return v

    @field_validator("avatar_url")
    @classmethod
    def _require_https(cls, v: HttpUrl | None) -> HttpUrl | None:
        if v is not None and v.scheme != "https":
            raise ValueError("avatar_url must use https")
        return v


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/me/clubhouse", tags=["clubhouse"])


def _build_profile_response(profile: PrivateUserProfile) -> ClubhouseProfileResponse:
    rankings_map = {
        "tennis": profile.rankings.tennis,
        "padel": profile.rankings.padel,
        "pickleball": profile.rankings.pickleball,
    }
    card_sports_raw = build_athlete_card_sports(rankings_map)
    card_sports = [AthleteCardSport(**s) for s in card_sports_raw]  # type: ignore[arg-type]

    total_matches, total_wins = compute_match_totals(profile.completed_matches)

    # NOTE: leagues_completed cache is capped at 20 — replace with uncapped
    # counter field in a future schema migration.
    leagues_completed_count = len(profile.leagues_completed)

    resume = AthleteResume(
        total_matches=total_matches,
        total_wins=total_wins,
        leagues_completed=leagues_completed_count,
        sports=card_sports,
    )

    return ClubhouseProfileResponse(
        uid=profile.uid,
        display_name=profile.name,
        avatar_url=str(profile.profile_url) if profile.profile_url else None,
        resume=resume,
    )


@router.get("/profile", response_model=ClubhouseProfileResponse)
def get_clubhouse_profile(
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
) -> ClubhouseProfileResponse:
    profile = users_repo.get_private_profile(current_user.uid)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return _build_profile_response(profile)


@router.patch("/profile", response_model=ClubhouseProfileResponse)
def patch_clubhouse_profile(
    request: UpdateClubhouseProfileRequest,
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
    region_config_repo: RegionConfigRepo = Depends(get_region_config_repo),
) -> ClubhouseProfileResponse:
    """Partial update of the caller's own profile fields.

    Updates any subset of ``display_name``, ``avatar_url``, ``area``, ``levels``
    and returns the refreshed ``ClubhouseProfileResponse``. ``levels`` are merged
    per-sport (unmentioned sports keep their existing level). A name change is
    eventually consistent across denormalized caches (no synchronous fan-out to
    match/ticker/leaderboard/offer/discovery name caches). ``rankings.*`` fields
    are never touched. Avatar cannot be cleared (send a new URL only).
    """
    if (
        request.display_name is None
        and request.avatar_url is None
        and request.area is None
        and request.levels is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="at least one field must be provided",
        )

    if request.area is not None:
        config = region_config_repo.get()
        if str(request.area) not in config.mapping:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"unknown area: {request.area}",
            )

    profile = users_repo.get_private_profile(current_user.uid)
    if profile is None or profile.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    updates = build_profile_update_paths(
        display_name=request.display_name,
        avatar_url=str(request.avatar_url) if request.avatar_url is not None else None,
        area=request.area,
        levels=request.levels,
        levels_fields_set=request.levels.model_fields_set if request.levels is not None else set(),
    )
    users_repo.update_profile(current_user.uid, updates)

    fresh = users_repo.get_private_profile(current_user.uid)
    if fresh is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return _build_profile_response(fresh)
