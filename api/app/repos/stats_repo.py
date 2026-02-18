"""
RP-03 — Option A: compute UserStats from cached profile data.

Stats are derived entirely from fields already present on PrivateUserProfile
(``journal_recent`` and ``completed_matches``).  No Firestore reads are made
here.  When a dedicated ``users/{uid}/stats`` document is introduced (Option B),
this class can be swapped out for one that extends RepoBase.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models.common import JournalEntrySummary
from app.models.enums import JournalEntryTypeEnum, MatchResultEnum
from app.models.stats import UserStats, WeeklyActivity
from app.models.user import PrivateUserProfile


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _compute_weekly_activity(
    entries: list[JournalEntrySummary],
    today: date,
) -> WeeklyActivity:
    """Build a 7-day activity map and streak from journal entry summaries.

    Days are keyed as ISO date strings (UTC).  The streak is the number of
    consecutive days ending today that have at least one activity logged.
    """
    # Initialise ordered 7-day window (oldest → newest) with empty lists.
    window: dict[str, list[str]] = {
        (today - timedelta(days=i)).isoformat(): [] for i in range(6, -1, -1)
    }

    for entry in entries:
        # created_at is always UTC-aware after GsmBaseModel normalisation.
        entry_date = entry.created_at.date()
        key = entry_date.isoformat()
        if key not in window:
            continue
        activity_type = entry.entry_type.value if entry.entry_type else "match"
        window[key].append(activity_type)

    # Streak = consecutive days from today backward with at least one activity.
    streak = 0
    for i in range(7):
        day_key = (today - timedelta(days=i)).isoformat()
        if window.get(day_key):
            streak += 1
        else:
            break

    return WeeklyActivity(days=window, streak_count=streak)


class StatsRepo:
    """Compute-on-read stats aggregation (Option A).

    Accepts a ``PrivateUserProfile`` that has already been loaded and returns a
    ``UserStats`` object without making any additional Firestore calls.

    Swap to a ``RepoBase`` subclass when a dedicated Firestore stats doc is
    introduced.
    """

    def compute_user_stats(self, profile: PrivateUserProfile) -> UserStats:
        today = _today_utc()
        weekly = _compute_weekly_activity(profile.journal_recent, today)

        total_matches = len(profile.completed_matches)
        total_wins = sum(1 for m in profile.completed_matches if m.result == MatchResultEnum.WIN)
        total_training = sum(
            1 for e in profile.journal_recent if e.entry_type == JournalEntryTypeEnum.TRAINING
        )

        return UserStats(
            uid=profile.uid,
            weekly_activity=weekly,
            north_star=profile.north_star_goal,
            total_matches=total_matches,
            total_wins=total_wins,
            total_training_sessions=total_training,
            current_streak=weekly.streak_count,
        )
