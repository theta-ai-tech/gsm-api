from datetime import datetime, timedelta, timezone

import pytest

from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.users_repo import UsersRepo
from app.services.journal_service import JournalService

pytestmark = [pytest.mark.integration]


def _make_journal_service(db) -> JournalService:
    return JournalService(
        users_repo=UsersRepo(db),
        journal_repo=JournalRepo(db),
        matches_repo=MatchesRepo(db),
        firestore_client=db,
    )


def _seed_user(
    db,
    uid: str,
    *,
    journal_recent: list[dict] | None = None,
    completed_matches: list[dict] | None = None,
) -> None:
    doc = {
        "uid": uid,
        "name": "Stats Test User",
        "email": f"{uid}@test.com",
    }
    if journal_recent is not None:
        doc["journalRecent"] = journal_recent
    if completed_matches is not None:
        doc["completedMatches"] = completed_matches
    db.collection("users").document(uid).set(doc)


def _journal_summary(
    entry_id: str,
    created_at: datetime,
    entry_type: str,
) -> dict:
    return {
        "entryId": entry_id,
        "createdAt": created_at,
        "title": f"Entry {entry_id}",
        "entryType": entry_type,
    }


def test_dashboard_stats_new_user_returns_zeroes(db) -> None:
    uid = "stats_new_user"
    _seed_user(db, uid)
    service = _make_journal_service(db)

    stats = service.get_dashboard_stats(uid)

    assert stats.uid == uid
    assert stats.total_matches == 0
    assert stats.total_wins == 0
    assert stats.total_training_sessions == 0
    assert stats.current_streak == 0
    assert len(stats.weekly_activity.days) == 7
    assert all(not activities for activities in stats.weekly_activity.days.values())


def test_dashboard_stats_three_consecutive_days_yields_streak_three(db) -> None:
    uid = "stats_streak_three"
    now = datetime.now(timezone.utc)
    journal_recent = [
        _journal_summary("e-yesterday", now - timedelta(days=1), "training"),
        _journal_summary("e-two-days-ago", now - timedelta(days=2), "match"),
        _journal_summary("e-today", now, "match"),
    ]
    _seed_user(db, uid, journal_recent=journal_recent)
    service = _make_journal_service(db)

    stats = service.get_dashboard_stats(uid)

    assert stats.current_streak == 3
    assert stats.total_training_sessions == 1


def test_dashboard_stats_weekly_activity_ignores_entries_older_than_seven_days(
    db,
) -> None:
    uid = "stats_older_than_week"
    now = datetime.now(timezone.utc)
    journal_recent = [
        _journal_summary("e-today", now, "match"),
        _journal_summary("e-six-days", now - timedelta(days=6), "training"),
        _journal_summary("e-eight-days", now - timedelta(days=8), "training"),
    ]
    _seed_user(db, uid, journal_recent=journal_recent)
    service = _make_journal_service(db)

    stats = service.get_dashboard_stats(uid)

    today_key = now.date().isoformat()
    six_days_key = (now - timedelta(days=6)).date().isoformat()
    eight_days_key = (now - timedelta(days=8)).date().isoformat()

    assert len(stats.weekly_activity.days) == 7
    assert eight_days_key not in stats.weekly_activity.days
    assert stats.weekly_activity.days[today_key] == ["match"]
    assert stats.weekly_activity.days[six_days_key] == ["training"]
    assert (
        sum(len(activities) for activities in stats.weekly_activity.days.values()) == 2
    )
