from functools import lru_cache

from google.cloud import firestore  # type: ignore[import-untyped,attr-defined]

from app.deps import get_settings
from app.repos.leagues_repo import LeaguesRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.users_repo import UsersRepo
from app.repos.journal_repo import JournalRepo


@lru_cache
def get_firestore_client() -> firestore.Client:
    settings = get_settings()
    return firestore.Client(project=settings.project_id)


def get_users_repo() -> UsersRepo:
    return UsersRepo(get_firestore_client())


def get_matches_repo() -> MatchesRepo:
    return MatchesRepo(get_firestore_client())


def get_leagues_repo() -> LeaguesRepo:
    return LeaguesRepo(get_firestore_client())


def get_journal_repo() -> JournalRepo:
    return JournalRepo(get_firestore_client())
