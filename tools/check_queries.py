import os

from google.cloud import firestore

from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from tools.seed_firestore import seed_all


def _require_emulator() -> None:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not host:
        raise RuntimeError("FIRESTORE_EMULATOR_HOST must be set for index checks")
    if not (host.startswith("localhost") or host.startswith("127.0.0.1")):
        raise RuntimeError("FIRESTORE_EMULATOR_HOST must point to localhost")
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT must be set for index checks")


def main() -> None:
    _require_emulator()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    client = firestore.Client(project=project)
    seed_all(client)

    matches_repo = MatchesRepo(client)
    journal_repo = JournalRepo(client)

    matches_repo.list_upcoming_for_user("user_ignatios", limit=10)
    matches_repo.list_completed_for_user("user_ignatios", limit=10)
    matches_repo.list_upcoming_for_league("padel-local-2025", limit=10)
    matches_repo.list_completed_for_league("padel-local-2025", limit=10)
    journal_repo.list_entries("user_ignatios", limit=10)

    print("OK: queries executed without index errors")


if __name__ == "__main__":
    main()
