from datetime import datetime

from app.models.base import GsmBaseModel


class WeeklyActivity(GsmBaseModel):
    """7-day activity map: keys are ISO date strings, values are activity types."""

    days: dict[str, list[str]] = {}  # {"2026-02-10": ["match", "training"], ...}
    streak_count: int = 0


class NorthStarGoal(GsmBaseModel):
    goal_text: str  # "Reduce double faults by 20%"
    progress_pct: float = 0.0  # 0.0–100.0
    created_at: datetime
    target_date: datetime | None = None


class UserStats(GsmBaseModel):
    uid: str
    weekly_activity: WeeklyActivity
    north_star: NorthStarGoal | None = None
    total_matches: int = 0
    total_wins: int = 0
    total_training_sessions: int = 0
    current_streak: int = 0
