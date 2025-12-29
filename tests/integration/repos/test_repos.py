import pytest

from app.repos.users_repo import UsersRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.journal_repo import JournalRepo
from app.models import PublicUserProfile, PrivateUserProfile

pytestmark = [pytest.mark.integration, pytest.mark.seeded]


def test_get_user_private_profile_self(firestore_client):
    repo = UsersRepo(firestore_client)
    profile = repo.get_private_profile("user_ignatios")
    assert isinstance(profile, PrivateUserProfile)
    assert profile.email
    assert profile.preferences.sports


def test_get_user_public_profile_other(firestore_client):
    repo = UsersRepo(firestore_client)
    profile = repo.get_public_profile("user_alice")
    assert isinstance(profile, PublicUserProfile)
    assert not hasattr(profile, "email")


def test_list_upcoming_matches_for_user_sorted(firestore_client):
    repo = MatchesRepo(firestore_client)
    matches = repo.list_upcoming_for_user("user_ignatios", limit=10)
    assert matches
    statuses = [m.status.value for m in matches]
    assert all(status == "scheduled" for status in statuses)
    scheduled_times = [m.scheduled_at for m in matches]
    assert scheduled_times == sorted(scheduled_times)


def test_list_completed_matches_for_user_sorted(firestore_client):
    repo = MatchesRepo(firestore_client)
    matches = repo.list_completed_for_user("user_ignatios", limit=10)
    assert matches
    statuses = [m.status.value for m in matches]
    assert all(status == "completed" for status in statuses)
    finished_times = [m.finished_at for m in matches]
    assert finished_times == sorted(finished_times, reverse=True)


def test_journal_entries_sorted(firestore_client):
    repo = JournalRepo(firestore_client)
    entries = repo.list_entries("user_ignatios", limit=10)
    assert entries
    created = [e.created_at for e in entries]
    assert created == sorted(created, reverse=True)
