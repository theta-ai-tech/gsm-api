"""
Tab 4 CLUBHOUSE router - Athlete Card & Resume endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies.repos import get_users_repo
from app.deps import get_current_user
from app.models.base import GsmBaseModel
from app.models.enums import SportEnum
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.clubhouse_service import build_athlete_card_sports, compute_match_totals


# ---------------------------------------------------------------------------
# Response models (endpoint-local, not shared)
# ---------------------------------------------------------------------------


class AthleteCardSport(GsmBaseModel):
    sport: SportEnum
    pts: int
    tier: str
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
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/me/clubhouse", tags=["clubhouse"])


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

    rankings_map = {
        "tennis": profile.rankings.tennis,
        "padel": profile.rankings.padel,
        "pickleball": profile.rankings.pickleball,
    }
    card_sports_raw = build_athlete_card_sports(rankings_map)
    card_sports = [AthleteCardSport(**s) for s in card_sports_raw]  # type: ignore[arg-type]

    total_matches, total_wins = compute_match_totals(profile.completed_matches)

    # TODO: profile.leagues_completed is a capped D2 cache (max 20 items).
    # Replace with an uncapped counter field (e.g. totalLeaguesCompleted) on the
    # user document once it exists. Using 0 as a safe fallback until then.
    leagues_completed_count = 0

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
