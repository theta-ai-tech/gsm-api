from __future__ import annotations

from app.constants import STREAK_MILESTONES
from app.models.common import SportRanking, UserCompletedMatchSummary


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
                "tier": ranking.tier.value if ranking.tier else "amateur",
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
    """Return (total_matches, total_wins).

    TODO: completedMatches is a capped D2 cache (max 10 items) and must not be
    used for lifetime totals.  Wire this up to uncapped counter fields on the
    user document (e.g. ``totalMatchesPlayed``, ``totalWins``) once they exist,
    or use a Firestore aggregation count query on the matches collection.
    Returning 0 as a safe fallback until then.
    """
    del completed_matches  # capped cache — not suitable for totals
    return 0, 0


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
