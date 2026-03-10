"""
Tab 3 LAB router — progression graph and scoring insights.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.constants import LAB_PROGRESSION_DEFAULT_LIMIT, LAB_PROGRESSION_MAX_LIMIT
from app.dependencies.repos import get_point_history_repo, get_tier_config_repo, get_users_repo
from app.deps import get_current_user
from app.models.base import GsmBaseModel
from app.models.common import PerSportRankings, SportRanking, UserCompletedMatchSummary
from app.models.enums import MatchResultEnum, SportEnum
from app.models.point_history import PointHistoryEntry
from app.models.tier import TierThreshold
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

router = APIRouter(prefix="/me/lab", tags=["lab"])

_401 = {"description": "Missing or invalid Firebase ID token"}


# ===== Dashboard helpers =====


class QuickStats(GsmBaseModel):
    total_matches: int
    wins: int
    losses: int
    win_rate: float
    current_streak: int
    streak_type: Literal["win", "loss"] | None = None


class DashboardResponse(GsmBaseModel):
    rankings: dict[str, SportRanking]
    quick_stats: dict[str, QuickStats]
    tier_thresholds: list[TierThreshold]


def _rankings_to_dict(rankings: PerSportRankings) -> dict[str, SportRanking]:
    result: dict[str, SportRanking] = {}
    for sport in SportEnum:
        ranking = getattr(rankings, sport.value, None)
        if ranking is not None:
            result[sport.value] = ranking
    return result


def _compute_quick_stats(
    completed_matches: list[UserCompletedMatchSummary],
) -> dict[str, QuickStats]:
    sport_matches: dict[str, list[UserCompletedMatchSummary]] = {}
    for m in completed_matches:
        sport_matches.setdefault(m.sport.value, []).append(m)

    result: dict[str, QuickStats] = {}
    for sport, matches in sport_matches.items():
        wins = sum(1 for m in matches if m.result == MatchResultEnum.WIN)
        losses = sum(1 for m in matches if m.result == MatchResultEnum.LOSS)
        total = len(matches)
        win_rate = round(wins / total, 4) if total > 0 else 0.0

        sorted_matches = sorted(matches, key=lambda m: m.finished_at, reverse=True)
        streak = 0
        streak_type: Literal["win", "loss"] | None = None
        if sorted_matches and sorted_matches[0].result in (
            MatchResultEnum.WIN,
            MatchResultEnum.LOSS,
        ):
            streak_type = "win" if sorted_matches[0].result == MatchResultEnum.WIN else "loss"
            expected = MatchResultEnum.WIN if streak_type == "win" else MatchResultEnum.LOSS
            for m in sorted_matches:
                if m.result == expected:
                    streak += 1
                else:
                    break

        result[sport] = QuickStats(
            total_matches=total,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            current_streak=streak,
            streak_type=streak_type,
        )
    return result


# ===== Cursor helpers =====


def _decode_cursor(cursor_str: str | None) -> dict | None:
    if not cursor_str:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor_str.encode()))
        created_at_raw = data.get("createdAt")
        if created_at_raw:
            data["createdAt"] = datetime.fromisoformat(created_at_raw)
        return data
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")


def _encode_cursor(entry: PointHistoryEntry) -> str:
    data = {"createdAt": entry.created_at.isoformat(), "entryId": entry.entry_id}
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


# ===== Response model =====


class ProgressionResponse(GsmBaseModel):
    sport: SportEnum
    entries: list[PointHistoryEntry]
    cursor: str | None = None
    has_more: bool = False


# ===== GET /me/lab/progression =====


@router.get(
    "/progression",
    response_model=ProgressionResponse,
    summary="Get point history for the progression graph",
    responses={
        400: {"description": "Invalid sport or cursor"},
        401: _401,
    },
)
def get_progression(
    sport: SportEnum = Query(..., description="Sport to filter by"),
    limit: int = Query(
        default=LAB_PROGRESSION_DEFAULT_LIMIT,
        ge=1,
        le=LAB_PROGRESSION_MAX_LIMIT,
        description="Maximum number of entries to return",
    ),
    cursor: str | None = Query(
        default=None, description="Pagination cursor from previous response"
    ),
    current_user: CurrentUser = Depends(get_current_user),
    point_history_repo: PointHistoryRepo = Depends(get_point_history_repo),
) -> ProgressionResponse:
    """
    Return paginated point history for the authenticated user and given sport,
    ordered by createdAt DESC (most recent first).

    Pass the `cursor` value from a previous response to fetch the next page.
    `has_more` indicates whether additional entries exist beyond the current page.
    """
    parsed_cursor = _decode_cursor(cursor)

    # Fetch one extra to detect whether more pages exist.
    entries = point_history_repo.list_entries(
        uid=current_user.uid,
        sport=sport,
        limit=limit + 1,
        cursor=parsed_cursor,
    )

    has_more = len(entries) > limit
    page = entries[:limit]
    next_cursor = _encode_cursor(page[-1]) if has_more else None

    return ProgressionResponse(
        sport=sport,
        entries=page,
        cursor=next_cursor,
        has_more=has_more,
    )


# ===== GET /me/lab/dashboard =====


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Get lab dashboard overview",
    responses={
        401: _401,
        404: {"description": "User profile not found"},
    },
)
def get_dashboard(
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
    tier_config_repo: TierConfigRepo = Depends(get_tier_config_repo),
) -> DashboardResponse:
    """
    Return a high-level overview of the authenticated user's standings across all sports.

    Includes per-sport rankings, quick stats derived from completed matches,
    and tier thresholds for the mobile client to render threshold markers.
    """
    profile = users_repo.get_private_profile(current_user.uid)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    tier_config = tier_config_repo.get()

    return DashboardResponse(
        rankings=_rankings_to_dict(profile.rankings),
        quick_stats=_compute_quick_stats(profile.completed_matches),
        tier_thresholds=tier_config.thresholds,
    )
