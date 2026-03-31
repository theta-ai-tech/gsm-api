from __future__ import annotations

from app.constants import STREAK_MILESTONES


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
