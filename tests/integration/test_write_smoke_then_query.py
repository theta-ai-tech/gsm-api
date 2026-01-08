from datetime import datetime, timezone

import pytest
from google.cloud import firestore

from app.models import MatchStatusEnum, SportEnum
from app.repos.matches_repo import MatchesRepo
from tools.seed_data import PRIMARY_LEAGUE_ID, PRIMARY_USER_UID, USER_ALICE

pytestmark = [pytest.mark.integration, pytest.mark.seeded]


def _delete_match_if_exists(client: firestore.Client, match_id: str) -> None:
    doc_ref = client.collection("matches").document(match_id)
    if doc_ref.get().exists:
        doc_ref.delete()


def test_insert_scheduled_match_then_upcoming_query_contains_it(
    seeded_firestore: firestore.Client,
) -> None:
    match_id = "match-write-smoke-upcoming"
    _delete_match_if_exists(seeded_firestore, match_id)

    scheduled_at = datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc)
    doc = {
        "sport": SportEnum.PADEL.value,
        "status": MatchStatusEnum.SCHEDULED.value,
        "scheduledAt": scheduled_at,
        "leagueId": PRIMARY_LEAGUE_ID,
        "participants": [
            {"uid": PRIMARY_USER_UID, "role": "player", "team": 1},
            {"uid": USER_ALICE.uid, "role": "player", "team": 2},
        ],
        "participantUids": [PRIMARY_USER_UID, USER_ALICE.uid],
    }
    seeded_firestore.collection("matches").document(match_id).set(doc)

    repo = MatchesRepo(seeded_firestore)
    matches = repo.list_upcoming_for_user(PRIMARY_USER_UID, limit=50)
    match_ids = [match.match_id for match in matches]
    assert match_id in match_ids, (
        "Inserted scheduled match should be returned in upcoming query"
    )

    scheduled_times = [match.scheduled_at for match in matches]
    assert scheduled_times == sorted(scheduled_times), (
        "Upcoming matches should be ordered by scheduled_at ascending after insert"
    )
    assert matches[0].match_id == match_id, (
        "Inserted scheduled match should be first when it is earliest"
    )


def test_insert_completed_match_then_completed_query_contains_it(
    seeded_firestore: firestore.Client,
) -> None:
    match_id = "match-write-smoke-completed"
    _delete_match_if_exists(seeded_firestore, match_id)

    finished_at = datetime(2020, 12, 31, 10, 0, tzinfo=timezone.utc)
    doc = {
        "sport": SportEnum.PADEL.value,
        "status": MatchStatusEnum.COMPLETED.value,
        "finishedAt": finished_at,
        "participants": [
            {"uid": PRIMARY_USER_UID, "role": "player", "team": 1},
            {"uid": USER_ALICE.uid, "role": "player", "team": 2},
        ],
        "participantUids": [PRIMARY_USER_UID, USER_ALICE.uid],
        "score": {
            "sets": [
                {"p1Games": 6, "p2Games": 4},
                {"p1Games": 6, "p2Games": 3},
            ]
        },
    }
    seeded_firestore.collection("matches").document(match_id).set(doc)

    repo = MatchesRepo(seeded_firestore)
    matches = repo.list_completed_for_user(PRIMARY_USER_UID, limit=50)
    match_ids = [match.match_id for match in matches]
    assert match_id in match_ids, (
        "Inserted completed match should be returned in completed query"
    )

    finished_times = [match.finished_at for match in matches]
    assert finished_times == sorted(finished_times, reverse=True), (
        "Completed matches should be ordered by finished_at descending after insert"
    )
    assert matches[0].match_id == match_id, (
        "Inserted completed match should be first when it is newest"
    )
