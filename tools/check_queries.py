import os

from google.cloud import firestore

from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from tools.seed_data import PRIMARY_LEAGUE_ID, PRIMARY_USER_UID
from tools.seed_firestore import seed_all


def _require_emulator() -> str:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not host:
        raise RuntimeError("FIRESTORE_EMULATOR_HOST must be set for query checks")
    if not (host.startswith("localhost") or host.startswith("127.0.0.1")):
        raise RuntimeError("FIRESTORE_EMULATOR_HOST must point to localhost")
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT must be set for query checks")
    return project


def _assert_sorted(values: list, reverse: bool = False, label: str = "") -> None:
    expected = sorted(values, reverse=reverse)
    assert values == expected, f"{label} not sorted as expected"


def main() -> None:
    project = _require_emulator()
    client = firestore.Client(project=project)
    seed_all(client)

    uid = PRIMARY_USER_UID
    league_id = PRIMARY_LEAGUE_ID

    matches_repo = MatchesRepo(client)
    journal_repo = JournalRepo(client)

    upcoming_user = matches_repo.list_upcoming_for_user(uid, limit=10)
    completed_user = matches_repo.list_completed_for_user(uid, limit=10)
    upcoming_league = matches_repo.list_upcoming_for_league(league_id, limit=10)
    completed_league = matches_repo.list_completed_for_league(league_id, limit=10)
    journal_entries = journal_repo.list_entries(uid, limit=10)

    if upcoming_user:
        assert all(match.scheduled_at for match in upcoming_user)
        _assert_sorted([match.scheduled_at for match in upcoming_user], label="upcoming_user")
        assert all(uid in match.participant_uids for match in upcoming_user)
    else:
        print("WARN: no upcoming matches for user")

    if completed_user:
        assert all(match.finished_at for match in completed_user)
        _assert_sorted(
            [match.finished_at for match in completed_user], reverse=True, label="completed_user"
        )
        assert all(uid in match.participant_uids for match in completed_user)
    else:
        print("WARN: no completed matches for user")

    if upcoming_league:
        assert all(match.scheduled_at for match in upcoming_league)
        _assert_sorted([match.scheduled_at for match in upcoming_league], label="upcoming_league")
        assert all(match.league_id == league_id for match in upcoming_league)
    else:
        print("WARN: no upcoming matches for league")

    if completed_league:
        assert all(match.finished_at for match in completed_league)
        _assert_sorted(
            [match.finished_at for match in completed_league], reverse=True, label="completed_league"
        )
        assert all(match.league_id == league_id for match in completed_league)
    else:
        print("WARN: no completed matches for league")

    if journal_entries:
        assert all(entry.created_at for entry in journal_entries)
        _assert_sorted(
            [entry.created_at for entry in journal_entries], reverse=True, label="journal_entries"
        )
        assert all(entry.uid == uid for entry in journal_entries)
    else:
        print("WARN: no journal entries for user")

    print(
        "OK: "
        f"user upcoming={len(upcoming_user)}, "
        f"user completed={len(completed_user)}, "
        f"league upcoming={len(upcoming_league)}, "
        f"league completed={len(completed_league)}, "
        f"journal={len(journal_entries)}"
    )


if __name__ == "__main__":
    main()
