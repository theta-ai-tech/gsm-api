import pytest
from google.cloud import firestore

from app.models import LeagueStatusEnum
from app.repos.users_repo import UsersRepo
from tools.seed_data import PRIMARY_USER_UID

pytestmark = [pytest.mark.integration, pytest.mark.seeded]


def test_user_leagues_by_status_from_denormalized_summaries(
    seeded_firestore: firestore.Client,
) -> None:
    repo = UsersRepo(seeded_firestore)
    profile = repo.get_private_profile(PRIMARY_USER_UID)

    assert profile is not None, "Expected a profile for the primary seeded user"
    assert profile.leagues_active, "Expected at least one active league summary"
    assert profile.leagues_completed, "Expected at least one completed league summary"

    for league in profile.leagues_active:
        assert league.status == LeagueStatusEnum.ACTIVE, (
            f"Active league {league.league_id} has status {league.status}"
        )

    for league in profile.leagues_completed:
        assert league.status == LeagueStatusEnum.COMPLETED, (
            f"Completed league {league.league_id} has status {league.status}"
        )

    active_ids = {league.league_id for league in profile.leagues_active}
    completed_ids = {league.league_id for league in profile.leagues_completed}
    overlap = active_ids & completed_ids
    assert not overlap, f"Active/completed leagues should not overlap: {overlap}"
