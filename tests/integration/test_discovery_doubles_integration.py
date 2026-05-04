"""Integration tests for the DISCOVERY feed with doubles filter (DBL-8).

Tests verify end-to-end behavior against the real Firestore emulator:
- Basic feed listing with broadcast_type badges
- Doubles filter (?match_type=doubles)
- Singles filter (?match_type=singles)
- Caller's own broadcast is excluded
- Annotation counts (nearby_count, doubles_count, find_fourth_count)

Requires: FIRESTORE_EMULATOR_HOST env var set (e.g. via ``make emu-all``)
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user
from app.dependencies.repos import (
    get_broadcasts_repo,
    get_firestore_client,
    get_matches_repo,
    get_offers_repo,
    get_users_repo,
)
from app.main import app
from app.models.enums import (
    BroadcastStatusEnum,
    BroadcastTypeEnum,
    MatchTypeEnum,
)
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

pytestmark = [pytest.mark.integration]

NOW = datetime.now(timezone.utc)
EXPIRES = NOW + timedelta(hours=4)

# UIDs used in this test module
VIEWER_UID = "disc_viewer"
PLAYER_B_UID = "disc_player_b"
PLAYER_C_UID = "disc_player_c"
PLAYER_D_UID = "disc_player_d"


# ===== Helpers =====


def _seed_user(db, uid: str, name: str) -> None:
    db.collection("users").document(uid).set(
        {
            "name": name,
            "email": f"{uid}@gsm.local",
            "rankings": {},
            "playTab": {
                "state": "DISCOVERY",
                "updatedAt": NOW,
            },
        }
    )


def _seed_broadcast(
    db,
    broadcast_id: str,
    owner_uid: str,
    owner_name: str,
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES,
    broadcast_type: BroadcastTypeEnum = BroadcastTypeEnum.FIND_OPPONENT,
) -> None:
    db.collection("broadcasts").document(broadcast_id).set(
        {
            "ownerUid": owner_uid,
            "ownerName": owner_name,
            "ownerRanking": None,
            "sport": "tennis",
            "matchType": match_type.value,
            "broadcastType": broadcast_type.value,
            "partnerUid": None,
            "availability": "today",
            "courtStatus": "have_court",
            "courtLocation": "Court A",
            "venueRef": None,
            "status": BroadcastStatusEnum.ACTIVE.value,
            "expiresAt": EXPIRES,
            "createdAt": NOW,
            "location": {"area": None, "geo": None, "radiusKm": None},
        }
    )


# ===== Fixtures =====


@pytest.fixture(autouse=True)
def _seed(db):
    """Seed test data and clean up after each test."""
    _seed_user(db, VIEWER_UID, "Viewer")
    _seed_user(db, PLAYER_B_UID, "Player B")
    _seed_user(db, PLAYER_C_UID, "Player C")
    _seed_user(db, PLAYER_D_UID, "Player D")

    _seed_broadcast(db, "bc_singles", PLAYER_B_UID, "Player B", MatchTypeEnum.SINGLES)
    _seed_broadcast(
        db,
        "bc_doubles",
        PLAYER_C_UID,
        "Player C",
        MatchTypeEnum.DOUBLES,
        BroadcastTypeEnum.FIND_OPPONENT,
    )
    _seed_broadcast(
        db,
        "bc_find_fourth",
        PLAYER_D_UID,
        "Player D",
        MatchTypeEnum.DOUBLES,
        BroadcastTypeEnum.FIND_FOURTH,
    )
    yield

    # Cleanup
    for uid in [VIEWER_UID, PLAYER_B_UID, PLAYER_C_UID, PLAYER_D_UID]:
        db.collection("users").document(uid).delete()
    for bc_id in ["bc_singles", "bc_doubles", "bc_find_fourth", "bc_own"]:
        db.collection("broadcasts").document(bc_id).delete()


@pytest.fixture
def discovery_client(db):
    app.dependency_overrides[get_users_repo] = lambda: UsersRepo(db)
    app.dependency_overrides[get_broadcasts_repo] = lambda: BroadcastsRepo(db)
    app.dependency_overrides[get_matches_repo] = lambda: MatchesRepo(db)
    app.dependency_overrides[get_offers_repo] = lambda: OffersRepo(db)
    app.dependency_overrides[get_firestore_client] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=VIEWER_UID, email="disc_viewer@gsm.local"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


# ===== Tests =====


class TestDiscoveryFeed:
    def test_discovery_returns_all_broadcasts(
        self, discovery_client: TestClient
    ) -> None:
        resp = discovery_client.get("/me/state")

        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "DISCOVERY"
        broadcasts = data["payload"]["broadcasts"]
        ids = {b["broadcast_id"] for b in broadcasts}
        assert {"bc_singles", "bc_doubles", "bc_find_fourth"}.issubset(ids)

    def test_broadcast_cards_carry_match_type_and_broadcast_type(
        self, discovery_client: TestClient
    ) -> None:
        resp = discovery_client.get("/me/state")

        assert resp.status_code == 200
        data = resp.json()
        by_id = {b["broadcast_id"]: b for b in data["payload"]["broadcasts"]}

        assert by_id["bc_singles"]["match_type"] == "singles"
        assert by_id["bc_singles"]["broadcast_type"] == "find_opponent"
        assert by_id["bc_doubles"]["match_type"] == "doubles"
        assert by_id["bc_doubles"]["broadcast_type"] == "find_opponent"
        assert by_id["bc_find_fourth"]["match_type"] == "doubles"
        assert by_id["bc_find_fourth"]["broadcast_type"] == "find_fourth"

    def test_annotation_counts(self, discovery_client: TestClient) -> None:
        resp = discovery_client.get("/me/state")

        assert resp.status_code == 200
        data = resp.json()
        ann = data["annotations"]
        assert ann["nearby_count"] == 3
        assert ann["doubles_count"] == 2
        assert ann["find_fourth_count"] == 1

    def test_doubles_filter_returns_only_doubles(
        self, discovery_client: TestClient
    ) -> None:
        resp = discovery_client.get("/me/state?match_type=doubles")

        assert resp.status_code == 200
        data = resp.json()
        broadcasts = data["payload"]["broadcasts"]
        for b in broadcasts:
            assert b["match_type"] == "doubles"
        ids = {b["broadcast_id"] for b in broadcasts}
        assert "bc_singles" not in ids
        assert {"bc_doubles", "bc_find_fourth"}.issubset(ids)

    def test_singles_filter_returns_only_singles(
        self, discovery_client: TestClient
    ) -> None:
        resp = discovery_client.get("/me/state?match_type=singles")

        assert resp.status_code == 200
        data = resp.json()
        broadcasts = data["payload"]["broadcasts"]
        for b in broadcasts:
            assert b["match_type"] == "singles"
        ids = {b["broadcast_id"] for b in broadcasts}
        assert "bc_singles" in ids
        assert "bc_doubles" not in ids
        assert "bc_find_fourth" not in ids

    def test_excludes_own_broadcast(self, db, discovery_client: TestClient) -> None:
        _seed_broadcast(db, "bc_own", VIEWER_UID, "Viewer")

        resp = discovery_client.get("/me/state")

        assert resp.status_code == 200
        data = resp.json()
        ids = {b["broadcast_id"] for b in data["payload"]["broadcasts"]}
        assert "bc_own" not in ids

    def test_invalid_match_type_returns_422(self, discovery_client: TestClient) -> None:
        resp = discovery_client.get("/me/state?match_type=badvalue")

        assert resp.status_code == 422
