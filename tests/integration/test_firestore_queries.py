from datetime import datetime, timezone

import pytest
from google.cloud import firestore

from app.models import MatchStatusEnum
from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from tools.seed_data import LEAGUE_TENNIS_LOCAL, PRIMARY_LEAGUE_ID, PRIMARY_USER_UID

pytestmark = [pytest.mark.integration, pytest.mark.seeded]


def _assert_sorted(values: list, reverse: bool = False, message: str = "") -> None:
    expected = sorted(values, reverse=reverse)
    assert values == expected, message or "Expected results to be sorted"


def test_list_upcoming_matches_for_user_filters_and_sorts(
    seeded_firestore: firestore.Client,
) -> None:
    repo = MatchesRepo(seeded_firestore)
    now_utc = datetime.now(timezone.utc)
    matches = repo.list_upcoming_for_user(PRIMARY_USER_UID, limit=50)
    assert len(matches) >= 2, "Expected at least 2 upcoming matches for seeded user"

    for match in matches:
        assert PRIMARY_USER_UID in match.participant_uids, (
            f"Match {match.match_id} is missing primary participant uid"
        )
        assert match.status == MatchStatusEnum.SCHEDULED, (
            f"Match {match.match_id} has unexpected status {match.status}"
        )
        assert match.scheduled_at is not None, (
            f"Match {match.match_id} is missing scheduled_at"
        )
        assert match.scheduled_at >= now_utc, (
            f"Match {match.match_id} scheduled_at is before now"
        )

    scheduled_times = [match.scheduled_at for match in matches]
    _assert_sorted(
        scheduled_times,
        message="Upcoming matches should be ordered by scheduled_at ascending",
    )


def test_list_completed_matches_for_user_filters_and_sorts(
    seeded_firestore: firestore.Client,
) -> None:
    repo = MatchesRepo(seeded_firestore)
    matches = repo.list_completed_for_user(PRIMARY_USER_UID, limit=50)
    assert len(matches) >= 2, "Expected at least 2 completed matches for seeded user"

    for match in matches:
        assert PRIMARY_USER_UID in match.participant_uids, (
            f"Match {match.match_id} is missing primary participant uid"
        )
        assert match.status == MatchStatusEnum.COMPLETED, (
            f"Match {match.match_id} has unexpected status {match.status}"
        )
        assert match.finished_at is not None, (
            f"Match {match.match_id} is missing finished_at"
        )

    finished_times = [match.finished_at for match in matches]
    _assert_sorted(
        finished_times,
        reverse=True,
        message="Completed matches should be ordered by finished_at descending",
    )


def test_list_upcoming_matches_for_league_filters_and_sorts(
    seeded_firestore: firestore.Client,
) -> None:
    repo = MatchesRepo(seeded_firestore)
    matches = repo.list_upcoming_for_league(PRIMARY_LEAGUE_ID, limit=50)
    assert len(matches) >= 2, "Expected at least 2 upcoming matches for seeded league"

    for match in matches:
        assert match.league_id == PRIMARY_LEAGUE_ID, (
            f"Match {match.match_id} has unexpected league_id {match.league_id}"
        )
        assert match.status == MatchStatusEnum.SCHEDULED, (
            f"Match {match.match_id} has unexpected status {match.status}"
        )
        assert match.scheduled_at is not None, (
            f"Match {match.match_id} is missing scheduled_at"
        )

    scheduled_times = [match.scheduled_at for match in matches]
    _assert_sorted(
        scheduled_times,
        message="Upcoming league matches should be ordered by scheduled_at ascending",
    )
    assert all(match.league_id != LEAGUE_TENNIS_LOCAL.league_id for match in matches), (
        "Upcoming league matches should not include other league matches"
    )


def test_list_completed_matches_for_league_filters_and_sorts(
    seeded_firestore: firestore.Client,
) -> None:
    repo = MatchesRepo(seeded_firestore)
    matches = repo.list_completed_for_league(PRIMARY_LEAGUE_ID, limit=50)
    assert len(matches) >= 2, "Expected at least 2 completed matches for seeded league"

    for match in matches:
        assert match.league_id == PRIMARY_LEAGUE_ID, (
            f"Match {match.match_id} has unexpected league_id {match.league_id}"
        )
        assert match.status == MatchStatusEnum.COMPLETED, (
            f"Match {match.match_id} has unexpected status {match.status}"
        )
        assert match.finished_at is not None, (
            f"Match {match.match_id} is missing finished_at"
        )

    finished_times = [match.finished_at for match in matches]
    _assert_sorted(
        finished_times,
        reverse=True,
        message="Completed league matches should be ordered by finished_at descending",
    )
    assert all(match.league_id != LEAGUE_TENNIS_LOCAL.league_id for match in matches), (
        "Completed league matches should not include other league matches"
    )


def test_journal_entries_sorted_and_match_owner(
    seeded_firestore: firestore.Client,
) -> None:
    repo = JournalRepo(seeded_firestore)
    uid = PRIMARY_USER_UID
    entries = repo.list_entries(uid, limit=10)
    assert entries, "Expected journal entries for seeded user"
    assert all(entry.created_at for entry in entries), (
        "All entries should have created_at"
    )
    _assert_sorted(
        [entry.created_at for entry in entries],
        reverse=True,
        message="Journal entries should be ordered by created_at descending",
    )
    assert all(entry.uid == uid for entry in entries), (
        "Entries should match the owner uid"
    )
