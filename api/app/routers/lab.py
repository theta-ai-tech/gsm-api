"""
Tab 3 LAB router — progression graph and scoring insights.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.constants import (
    LAB_PROGRESSION_DEFAULT_LIMIT,
    LAB_PROGRESSION_MAX_LIMIT,
    LAB_RIVALRY_DEFAULT_LIMIT,
    LAB_RIVALRY_MAX_LIMIT,
    TICKER_LIST_DEFAULT_LIMIT,
    TICKER_LIST_MAX_LIMIT,
)
from app.dependencies.repos import (
    get_leaderboard_repo,
    get_matches_repo,
    get_point_history_repo,
    get_region_config_repo,
    get_scouting_repo,
    get_ticker_repo,
    get_tier_config_repo,
    get_users_repo,
)
from app.deps import get_current_user
from app.models.base import GsmBaseModel
from app.models.common import PerSportRankings, SportRanking, UserCompletedMatchSummary
from app.models.enums import MatchResultEnum, SportEnum, TierEnum
from app.models.leaderboard import LeaderboardEntry, RisingStarEntry
from app.models.match import Match, compute_participant_pair
from app.models.point_history import PointHistoryEntry
from app.models.skill_dna import SportSkillDna
from app.models.ticker import TickerEvent
from app.models.tier import TierConfig, TierThreshold
from app.repos.leaderboard_repo import LeaderboardRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.scouting_repo import ScoutingRepo
from app.repos.ticker_repo import TickerRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.scoring_service import win_probability
from app.services.scouting_service import compute_confidence, sorted_tag_list, tag_label

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


# ===== Skill DNA helpers =====

_AXES = ("serve", "power", "net_play", "stamina", "mental")
_MIN_DATA_POINTS = 3


class SkillAxisResponse(GsmBaseModel):
    positive: int
    negative: int
    score: int


class ComparisonData(GsmBaseModel):
    label: str
    axes: dict[str, int]


class SkillDnaResponse(GsmBaseModel):
    sport: SportEnum
    axes: dict[str, SkillAxisResponse]
    total_reflections: int
    comparison: ComparisonData | None = None
    insufficient_axes: list[str] = []


def _build_axes(sport_dna: SportSkillDna) -> tuple[dict[str, SkillAxisResponse], list[str]]:
    """Return (axes_dict, insufficient_axes) from a SportSkillDna instance."""
    axes: dict[str, SkillAxisResponse] = {}
    insufficient: list[str] = []
    for axis in _AXES:
        axis_data = getattr(sport_dna, axis, None)
        if axis_data is not None:
            axes[axis] = SkillAxisResponse(
                positive=axis_data.positive,
                negative=axis_data.negative,
                score=axis_data.score,
            )
            if axis_data.positive + axis_data.negative < _MIN_DATA_POINTS:
                insufficient.append(axis)
    return axes, insufficient


def _resolve_comparison(
    tier_config_repo: TierConfigRepo,
    tier_config: TierConfig,
    current_tier: TierEnum | None,
    sport: SportEnum,
) -> ComparisonData | None:
    """Look up the next-tier-up average for the given sport. Returns None if unavailable."""
    if current_tier is None:
        return None

    thresholds = tier_config.thresholds
    current_idx = next((i for i, t in enumerate(thresholds) if t.tier == current_tier), None)
    if current_idx is None or current_idx >= len(thresholds) - 1:
        return None  # Already at top tier or tier not found

    next_threshold = thresholds[current_idx + 1]
    next_tier = next_threshold.tier

    tier_averages = tier_config_repo.get_tier_averages()
    if not tier_averages:
        return None

    tier_data = tier_averages.get(next_tier.value) or {}
    sport_averages: dict[str, int] = tier_data.get(sport.value) or {}
    if not sport_averages:
        return None

    return ComparisonData(label=f"{next_threshold.label} Average", axes=sport_averages)


# ===== GET /me/lab/skill-dna =====


@router.get(
    "/skill-dna",
    response_model=SkillDnaResponse,
    summary="Get Skill DNA radar chart data for a sport",
    responses={
        400: {"description": "Invalid sport"},
        401: _401,
        404: {"description": "User profile not found or no Skill DNA data for sport"},
    },
)
def get_skill_dna(
    sport: SportEnum = Query(..., description="Sport to retrieve Skill DNA for"),
    compare: Literal["next_tier"] | None = Query(
        default=None, description="Optional comparison mode"
    ),
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
    tier_config_repo: TierConfigRepo = Depends(get_tier_config_repo),
) -> SkillDnaResponse:
    """
    Return the authenticated user's Skill DNA radar chart data for the given sport.

    Axes with fewer than 3 data points are listed in `insufficientAxes` to indicate
    the score is not yet statistically meaningful.

    Pass `compare=next_tier` to include the next tier's average scores for comparison.
    Comparison data is only available after LAB-8 seeds `config/tierAverages`.
    """
    profile = users_repo.get_public_profile(current_user.uid)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    skill_dna = profile.skill_dna or {}
    sport_dna = skill_dna.get(sport.value)
    if sport_dna is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Skill DNA data found for sport: {sport.value}",
        )

    axes, insufficient = _build_axes(sport_dna)

    comparison: ComparisonData | None = None
    if compare == "next_tier":
        sport_ranking = getattr(profile.rankings, sport.value, None)
        current_tier = sport_ranking.tier if sport_ranking else None
        tier_config = tier_config_repo.get()
        comparison = _resolve_comparison(tier_config_repo, tier_config, current_tier, sport)

    return SkillDnaResponse(
        sport=sport,
        axes=axes,
        total_reflections=sport_dna.total_reflections,
        comparison=comparison,
        insufficient_axes=insufficient,
    )


# ===== Rivalry helpers =====


def _score_text(match: Match) -> str | None:
    """Render a human-readable score string from a Match, e.g. '6-4, 3-6, 7-5'."""
    if not match.score or not match.score.sets:
        return None
    return ", ".join(f"{s.p1_games}-{s.p2_games}" for s in match.score.sets)


def _dna_axis_scores(sport_dna: SportSkillDna | None) -> dict[str, int]:
    """Return {axis: score} for all axes that have data."""
    if sport_dna is None:
        return {}
    result: dict[str, int] = {}
    for axis in _AXES:
        axis_data = getattr(sport_dna, axis, None)
        if axis_data is not None:
            result[axis] = axis_data.score
    return result


# ===== Rivalry response models =====


class RivalryPlayerInfo(GsmBaseModel):
    uid: str
    name: str
    pts: int
    tier: TierEnum | None = None


class HeadToHead(GsmBaseModel):
    my_wins: int
    opponent_wins: int
    total_matches: int


class RivalryMatch(GsmBaseModel):
    match_id: str
    finished_at: datetime
    score_text: str | None = None
    result: MatchResultEnum | None = None


class SkillDnaOverlay(GsmBaseModel):
    me: dict[str, int]
    opponent: dict[str, int]


class RivalryResponse(GsmBaseModel):
    sport: SportEnum
    me: RivalryPlayerInfo
    opponent: RivalryPlayerInfo
    win_probability: float
    head_to_head: HeadToHead
    recent_matches: list[RivalryMatch]
    skill_dna_comparison: SkillDnaOverlay | None = None


# ===== GET /me/lab/rivalry/{opponent_uid} =====


@router.get(
    "/rivalry/{opponent_uid}",
    response_model=RivalryResponse,
    summary="Get head-to-head rivalry breakdown against an opponent",
    responses={
        400: {"description": "Invalid sport"},
        401: _401,
        404: {"description": "Opponent profile not found"},
    },
)
def get_rivalry(
    opponent_uid: str,
    sport: SportEnum = Query(..., description="Sport to analyse"),
    limit: int = Query(
        default=LAB_RIVALRY_DEFAULT_LIMIT,
        ge=1,
        le=LAB_RIVALRY_MAX_LIMIT,
        description="Max recent matches to return",
    ),
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
    matches_repo: MatchesRepo = Depends(get_matches_repo),
) -> RivalryResponse:
    """
    Return a head-to-head breakdown between the authenticated user and an opponent.

    Includes win probability, H2H record, recent match results, and Skill DNA overlay
    for both players (when available).
    """
    my_uid = current_user.uid

    my_profile = users_repo.get_public_profile(my_uid)
    if my_profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    opp_profile = users_repo.get_public_profile(opponent_uid)
    if opp_profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Opponent profile not found"
        )

    my_ranking = getattr(my_profile.rankings, sport.value, None)
    opp_ranking = getattr(opp_profile.rankings, sport.value, None)

    my_pts = my_ranking.pts if my_ranking else 1000
    opp_pts = opp_ranking.pts if opp_ranking else 1000

    pair = compute_participant_pair([my_uid, opponent_uid])
    h2h_matches = matches_repo.list_head_to_head(pair or "", sport, limit=limit) if pair else []

    my_wins = sum(
        1 for m in h2h_matches if (m.result_by_user or {}).get(my_uid) == MatchResultEnum.WIN
    )
    opp_wins = sum(
        1 for m in h2h_matches if (m.result_by_user or {}).get(opponent_uid) == MatchResultEnum.WIN
    )

    recent_matches = [
        RivalryMatch(
            match_id=m.match_id,
            finished_at=m.finished_at,  # type: ignore[arg-type]
            score_text=_score_text(m),
            result=(m.result_by_user or {}).get(my_uid),
        )
        for m in h2h_matches
    ]

    my_dna = (my_profile.skill_dna or {}).get(sport.value)
    opp_dna = (opp_profile.skill_dna or {}).get(sport.value)
    my_scores = _dna_axis_scores(my_dna)
    opp_scores = _dna_axis_scores(opp_dna)
    skill_dna_comparison = (
        SkillDnaOverlay(me=my_scores, opponent=opp_scores) if my_scores or opp_scores else None
    )

    return RivalryResponse(
        sport=sport,
        me=RivalryPlayerInfo(
            uid=my_uid,
            name=my_profile.name,
            pts=my_pts,
            tier=my_ranking.tier if my_ranking else None,
        ),
        opponent=RivalryPlayerInfo(
            uid=opponent_uid,
            name=opp_profile.name,
            pts=opp_pts,
            tier=opp_ranking.tier if opp_ranking else None,
        ),
        win_probability=win_probability(my_pts, opp_pts),
        head_to_head=HeadToHead(
            my_wins=my_wins,
            opponent_wins=opp_wins,
            total_matches=len(h2h_matches),
        ),
        recent_matches=recent_matches,
        skill_dna_comparison=skill_dna_comparison,
    )


# ===== Scouting response models =====


class ScoutingTagResponse(GsmBaseModel):
    tag: str
    count: int
    label: str


class ScoutingResponse(GsmBaseModel):
    uid: str
    sport: SportEnum
    weak: list[ScoutingTagResponse]
    strong: list[ScoutingTagResponse]
    total_reports: int
    unique_reporters: int
    last_updated: datetime | None = None
    confidence: Literal["low", "medium", "high"]


# ===== GET /me/lab/scouting/{opponent_uid} =====


@router.get(
    "/scouting/{opponent_uid}",
    response_model=ScoutingResponse,
    summary="Get community scouting report for an opponent",
    responses={
        401: _401,
        404: {"description": "No scouting data found for this opponent/sport"},
        422: {"description": "Invalid sport"},
    },
)
def get_scouting(
    opponent_uid: str,
    sport: SportEnum = Query(..., description="Sport to filter by"),
    current_user: CurrentUser = Depends(get_current_user),
    scouting_repo: ScoutingRepo = Depends(get_scouting_repo),
) -> ScoutingResponse:
    """
    Return the community scouting report for a specific opponent and sport.

    Tags are sorted by count descending. Confidence level is derived from
    the total number of reports: low (< 3), medium (3-7), high (> 7).
    """
    profile = scouting_repo.get_profile(opponent_uid)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No scouting data found for this opponent",
        )

    sport_data = getattr(profile, sport.value, None)
    if sport_data is None or sport_data.total_reports == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scouting data found for sport: {sport.value}",
        )

    weak_sorted = sorted_tag_list(sport_data.weak)
    strong_sorted = sorted_tag_list(sport_data.strong)

    return ScoutingResponse(
        uid=opponent_uid,
        sport=sport,
        weak=[
            ScoutingTagResponse(tag=tag, count=count, label=tag_label(tag))
            for tag, count in weak_sorted
        ],
        strong=[
            ScoutingTagResponse(tag=tag, count=count, label=tag_label(tag))
            for tag, count in strong_sorted
        ],
        total_reports=sport_data.total_reports,
        unique_reporters=sport_data.unique_reporters,
        last_updated=sport_data.last_updated,
        confidence=compute_confidence(sport_data.total_reports),
    )


# ===== Leaderboard response model =====


class LeaderboardResponse(GsmBaseModel):
    region: str
    sport: SportEnum
    entries: list[LeaderboardEntry]
    rising_stars: list[RisingStarEntry]
    last_updated: datetime | None = None


# ===== GET /me/lab/leaderboard =====


def _resolve_region(
    region_param: str | None,
    current_user: CurrentUser,
    users_repo: UsersRepo,
    region_config_repo: RegionConfigRepo,
) -> str:
    """Resolve the region string from the query param or user preferences."""
    if region_param is not None:
        return region_param

    profile = users_repo.get_private_profile(current_user.uid)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found; cannot determine default region",
        )

    area_code = str(profile.preferences.area)
    config = region_config_repo.get()
    region = config.mapping.get(area_code)
    if region is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No region mapping found for area code: {area_code}",
        )
    return region


@router.get(
    "/leaderboard",
    response_model=LeaderboardResponse,
    summary="Get regional leaderboard for a sport",
    responses={
        401: _401,
        404: {"description": "No leaderboard found for region/sport combination"},
        422: {"description": "Invalid sport"},
    },
)
def get_leaderboard(
    sport: SportEnum = Query(..., description="Sport to retrieve leaderboard for"),
    region: str | None = Query(
        default=None,
        description="Region slug (e.g. 'athens'). Defaults to user's area if omitted.",
    ),
    current_user: CurrentUser = Depends(get_current_user),
    leaderboard_repo: LeaderboardRepo = Depends(get_leaderboard_repo),
    users_repo: UsersRepo = Depends(get_users_repo),
    region_config_repo: RegionConfigRepo = Depends(get_region_config_repo),
) -> LeaderboardResponse:
    """
    Return the regional leaderboard for the given sport.

    If `region` is omitted the endpoint defaults to the region mapped from the
    authenticated user's `preferences.area` via the `config/regions` document.

    Returns 404 when no leaderboard document exists for the region/sport pair.
    """
    resolved_region = _resolve_region(region, current_user, users_repo, region_config_repo)

    snapshot = leaderboard_repo.get_snapshot(resolved_region, sport.value)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No leaderboard found for region={resolved_region}, sport={sport.value}",
        )

    return LeaderboardResponse(
        region=snapshot.region,
        sport=snapshot.sport,
        entries=snapshot.entries,
        rising_stars=snapshot.rising_stars,
        last_updated=snapshot.last_updated,
    )


# ===== Ticker response model =====


class TickerResponse(GsmBaseModel):
    events: list[TickerEvent]
    region: str
    sport: SportEnum


# ===== GET /me/lab/ticker =====


@router.get(
    "/ticker",
    response_model=TickerResponse,
    summary="Get recent ticker events for the Global Upsets feed",
    responses={
        401: _401,
        404: {"description": "Cannot determine default region for user"},
        422: {"description": "Invalid sport"},
    },
)
def get_ticker(
    sport: SportEnum = Query(..., description="Sport to filter by"),
    region: str | None = Query(
        default=None,
        description="Region slug (e.g. 'athens'). Defaults to user's area if omitted.",
    ),
    limit: int = Query(
        default=TICKER_LIST_DEFAULT_LIMIT,
        ge=1,
        le=TICKER_LIST_MAX_LIMIT,
        description="Maximum number of events to return",
    ),
    current_user: CurrentUser = Depends(get_current_user),
    ticker_repo: TickerRepo = Depends(get_ticker_repo),
    users_repo: UsersRepo = Depends(get_users_repo),
    region_config_repo: RegionConfigRepo = Depends(get_region_config_repo),
) -> TickerResponse:
    """
    Return recent ticker events for the given sport and region, ordered by
    createdAt DESC (most recent first). Expired events are excluded server-side.

    If `region` is omitted the endpoint defaults to the region mapped from the
    authenticated user's `preferences.area` via the `config/regions` document.
    """
    resolved_region = _resolve_region(region, current_user, users_repo, region_config_repo)

    events = ticker_repo.list_by_region_sport(
        region=resolved_region,
        sport=sport.value,
        limit=limit,
    )

    return TickerResponse(
        events=events,
        region=resolved_region,
        sport=sport,
    )
