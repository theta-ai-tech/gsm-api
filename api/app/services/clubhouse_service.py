from __future__ import annotations

from typing import Any

from app.constants import STREAK_MILESTONES
from app.models.common import PerSportLevels, SportRanking, UserCompletedMatchSummary
from app.models.enums import MatchResultEnum


def build_athlete_card_sports(
    rankings_by_sport: dict[str, SportRanking | None],
) -> list[dict[str, object]]:
    """Build per-sport athlete card data from the user's rankings map.

    Returns a list of dicts with keys matching AthleteCardSport fields.
    Only sports where the user has a ranking are included.
    """
    result: list[dict[str, object]] = []
    for sport_key in ("tennis", "padel", "pickleball"):
        ranking = rankings_by_sport.get(sport_key)
        if ranking is None:
            continue
        result.append(
            {
                "sport": ranking.sport,
                "pts": ranking.pts,
                "tier": ranking.tier.value if ranking.tier else None,
                "global_ranking": ranking.global_ranking,
                "personal_best": ranking.personal_best,
                "current_streak": ranking.current_streak,
                "best_streak": ranking.best_streak,
            }
        )
    return result


def compute_match_totals(
    completed_matches: list[UserCompletedMatchSummary],
) -> tuple[int, int]:
    """Return (total_matches, total_wins) from the completed-matches cache.

    # NOTE: completedMatches cache is capped at 10 — counts are accurate for
    # most users; replace with uncapped counter field in a future schema migration.
    """
    total = len(completed_matches)
    wins = sum(1 for m in completed_matches if m.result == MatchResultEnum.WIN)
    return total, wins


def build_profile_update_paths(
    display_name: str | None,
    avatar_url: str | None,
    area: int | None,
    levels: PerSportLevels | None,
    levels_fields_set: set[str],
) -> dict[str, Any]:
    """Map validated PATCH-profile fields to camelCase Firestore dot-paths.

    Levels are merged per-sport (one dot-path per provided sport), never a whole
    map replace, so unmentioned sports keep their existing level. ``nameLower`` is
    written in lockstep with ``name`` to keep the player prefix-search index in
    sync. This function never emits any ``rankings.*`` path.

    ``display_name`` is expected to be already stripped by the request model, and
    ``avatar_url`` already ``str(...)``-converted by the caller.
    """
    updates: dict[str, Any] = {}
    if display_name is not None:
        updates["name"] = display_name
        updates["nameLower"] = display_name.lower()
    if avatar_url is not None:
        updates["profileUrl"] = avatar_url
    if area is not None:
        updates["preferences.area"] = area
    if levels is not None:
        for sport in ("tennis", "padel", "pickleball"):
            if sport in levels_fields_set:
                value = getattr(levels, sport)
                if value is not None:
                    updates[f"preferences.levels.{sport}"] = value.value
    return updates


def check_personal_best(new_pts: int, current_best: int | None) -> tuple[bool, int]:
    if current_best is None or new_pts > current_best:
        return True, new_pts
    return False, current_best


def update_streak_on_win(current_streak: int, best_streak: int) -> tuple[int, int]:
    new_current = current_streak + 1
    new_best = max(new_current, best_streak)
    return new_current, new_best


def update_streak_on_loss(current_streak: int, best_streak: int) -> tuple[int, int]:
    del current_streak
    return 0, best_streak


def is_streak_milestone(streak: int) -> bool:
    return streak in STREAK_MILESTONES
