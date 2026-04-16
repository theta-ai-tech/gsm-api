from functools import lru_cache

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.deps import get_settings
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.journal_repo import JournalRepo
from app.repos.leagues_repo import LeaguesRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.leaderboard_repo import LeaderboardRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.scouting_repo import ScoutingRepo
from app.repos.ticker_repo import TickerRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.repos.venue_repo import VenueRepo


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


def get_broadcasts_repo() -> BroadcastsRepo:
    return BroadcastsRepo(get_firestore_client())


def get_offers_repo() -> OffersRepo:
    return OffersRepo(get_firestore_client())


def get_point_history_repo() -> PointHistoryRepo:
    return PointHistoryRepo(get_firestore_client())


def get_leaderboard_repo() -> LeaderboardRepo:
    return LeaderboardRepo(get_firestore_client())


def get_scouting_repo() -> ScoutingRepo:
    return ScoutingRepo(get_firestore_client())


def get_region_config_repo() -> RegionConfigRepo:
    return RegionConfigRepo(get_firestore_client())


def get_ticker_repo() -> TickerRepo:
    return TickerRepo(get_firestore_client())


def get_tier_config_repo() -> TierConfigRepo:
    return TierConfigRepo(get_firestore_client())


def get_venue_repo() -> VenueRepo:
    return VenueRepo(get_firestore_client())
