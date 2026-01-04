import os

import pytest
from google.cloud import firestore

from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from tools.seed_data import PRIMARY_LEAGUE_ID, PRIMARY_USER_UID
from tools.seed_firestore import seed_all

pytestmark = [pytest.mark.integration, pytest.mark.seeded]


def _assert_sorted(values: list, reverse: bool = False) -> None:
    assert values == sorted(values, reverse=reverse)


@pytest.fixture(scope="session")
def firestore_client() -> firestore.Client:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "gsm-dev-fake")
    client = firestore.Client(project=project)
    seed_all(client)
    return client


def test_upcoming_matches_sorted_and_contains_user(
    firestore_client: firestore.Client,
) -> None:
    repo = MatchesRepo(firestore_client)
    uid = PRIMARY_USER_UID
    matches = repo.list_upcoming_for_user(uid, limit=10)
    assert matches
    assert all(match.scheduled_at for match in matches)
    _assert_sorted([match.scheduled_at for match in matches])
    assert all(uid in match.participant_uids for match in matches)


def test_completed_matches_sorted_and_contains_user(
    firestore_client: firestore.Client,
) -> None:
    repo = MatchesRepo(firestore_client)
    uid = PRIMARY_USER_UID
    matches = repo.list_completed_for_user(uid, limit=10)
    assert matches
    assert all(match.finished_at for match in matches)
    _assert_sorted([match.finished_at for match in matches], reverse=True)
    assert all(uid in match.participant_uids for match in matches)


def test_league_upcoming_matches_sorted_and_match_league(
    firestore_client: firestore.Client,
) -> None:
    repo = MatchesRepo(firestore_client)
    league_id = PRIMARY_LEAGUE_ID
    matches = repo.list_upcoming_for_league(league_id, limit=10)
    assert matches
    assert all(match.scheduled_at for match in matches)
    _assert_sorted([match.scheduled_at for match in matches])
    assert all(match.league_id == league_id for match in matches)


def test_league_completed_matches_sorted_and_match_league(
    firestore_client: firestore.Client,
) -> None:
    repo = MatchesRepo(firestore_client)
    league_id = PRIMARY_LEAGUE_ID
    matches = repo.list_completed_for_league(league_id, limit=10)
    assert matches
    assert all(match.finished_at for match in matches)
    _assert_sorted([match.finished_at for match in matches], reverse=True)
    assert all(match.league_id == league_id for match in matches)


def test_journal_entries_sorted_and_match_owner(
    firestore_client: firestore.Client,
) -> None:
    repo = JournalRepo(firestore_client)
    uid = PRIMARY_USER_UID
    entries = repo.list_entries(uid, limit=10)
    assert entries
    assert all(entry.created_at for entry in entries)
    _assert_sorted([entry.created_at for entry in entries], reverse=True)
    assert all(entry.uid == uid for entry in entries)
