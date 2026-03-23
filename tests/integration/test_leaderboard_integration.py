"""
Integration tests for GET /me/lab/leaderboard.

Seeds leaderboard, user, and region config documents into the Firestore emulator,
then calls the endpoint via FastAPI's TestClient to verify all acceptance criteria.

Requires: FIRESTORE_EMULATOR_HOST env var (e.g. via `make emu-firestore`)

Run:
    make test-int
    # or just this file:
    pytest tests/integration/test_leaderboard_integration.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import (
    get_leaderboard_repo,
    get_region_config_repo,
    get_users_repo,
)
from app.deps import get_current_user
from app.main import app
from app.repos.leaderboard_repo import LeaderboardRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

pytestmark = [pytest.mark.integration]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MY_UID = "lb_test_user"
_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_leaderboard(db, region: str, sport: str) -> None:
    doc_id = f"{region}_{sport}"
    db.collection("leaderboards").document(doc_id).set(
        {
            "region": region,
            "sport": sport,
            "entries": [
                {
                    "uid": "user_123",
                    "name": "Alex",
                    "pts": 3450,
                    "tier": "advanced",
                    "rank": 1,
                    "delta7d": 250,
                },
                {
                    "uid": "user_456",
                    "name": "Ben",
                    "pts": 3100,
                    "tier": "intermediate",
                    "rank": 2,
                    "delta7d": -50,
                },
            ],
            "risingStars": [
                {
                    "uid": "user_789",
                    "name": "Dana",
                    "pts": 2100,
                    "delta7d": 400,
                    "rank": 15,
                },
            ],
            "lastUpdated": _NOW,
        }
    )


def _seed_user(db, uid: str, area: int = 101) -> None:
    db.collection("users").document(uid).set(
        {
            "uid": uid,
            "name": "Test User",
            "email": "test@example.com",
            "rankings": {},
            "preferences": {
                "area": area,
                "levels": {},
                "sports": [],
            },
        }
    )


def _seed_region_config(db) -> None:
    db.collection("config").document("regions").set(
        {
            "mapping": {"101": "athens", "202": "thessaloniki"},
            "version": 1,
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_lb(db):
    yield
    for doc_id in ("athens_tennis", "athens_padel", "london_tennis"):
        db.collection("leaderboards").document(doc_id).delete()
    for uid in (_MY_UID,):
        db.collection("users").document(uid).delete()
    db.collection("config").document("regions").delete()


@pytest.fixture
def lb_client(db):
    mock_user = CurrentUser(uid=_MY_UID, email="me@test.com")
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_leaderboard_repo] = lambda: LeaderboardRepo(db)
    app.dependency_overrides[get_users_repo] = lambda: UsersRepo(db)
    app.dependency_overrides[get_region_config_repo] = lambda: RegionConfigRepo(db)
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# LB-01: Basic response shape with explicit region
# ---------------------------------------------------------------------------


class TestLeaderboardShape:
    def test_returns_200_with_explicit_region(self, lb_client, db) -> None:
        _seed_leaderboard(db, "athens", "tennis")

        resp = lb_client.get("/me/lab/leaderboard?sport=tennis&region=athens")

        assert resp.status_code == 200

    def test_top_level_fields_present(self, lb_client, db) -> None:
        _seed_leaderboard(db, "athens", "tennis")

        body = lb_client.get("/me/lab/leaderboard?sport=tennis&region=athens").json()

        assert body["region"] == "athens"
        assert body["sport"] == "tennis"
        assert isinstance(body["entries"], list)
        assert isinstance(body["rising_stars"], list)
        assert body["last_updated"] is not None

    def test_entry_fields(self, lb_client, db) -> None:
        _seed_leaderboard(db, "athens", "tennis")

        body = lb_client.get("/me/lab/leaderboard?sport=tennis&region=athens").json()

        entry = body["entries"][0]
        assert entry["uid"] == "user_123"
        assert entry["name"] == "Alex"
        assert entry["pts"] == 3450
        assert entry["tier"] == "advanced"
        assert entry["rank"] == 1
        assert entry["delta7d"] == 250

    def test_rising_star_fields(self, lb_client, db) -> None:
        _seed_leaderboard(db, "athens", "tennis")

        body = lb_client.get("/me/lab/leaderboard?sport=tennis&region=athens").json()

        star = body["rising_stars"][0]
        assert star["uid"] == "user_789"
        assert star["name"] == "Dana"
        assert star["pts"] == 2100
        assert star["delta7d"] == 400
        assert star["rank"] == 15


# ---------------------------------------------------------------------------
# LB-02: Region defaulting from user preferences
# ---------------------------------------------------------------------------


class TestRegionDefaulting:
    def test_defaults_region_from_user_area(self, lb_client, db) -> None:
        _seed_user(db, _MY_UID, area=101)
        _seed_region_config(db)
        _seed_leaderboard(db, "athens", "tennis")

        resp = lb_client.get("/me/lab/leaderboard?sport=tennis")

        assert resp.status_code == 200
        assert resp.json()["region"] == "athens"

    def test_explicit_region_overrides_default(self, lb_client, db) -> None:
        _seed_user(db, _MY_UID, area=101)
        _seed_region_config(db)
        _seed_leaderboard(db, "athens", "tennis")
        _seed_leaderboard(db, "london", "tennis")

        resp = lb_client.get("/me/lab/leaderboard?sport=tennis&region=london")

        assert resp.status_code == 200
        assert resp.json()["region"] == "london"


# ---------------------------------------------------------------------------
# LB-03: Error cases
# ---------------------------------------------------------------------------


class TestLeaderboardErrors:
    def test_no_leaderboard_returns_404(self, lb_client) -> None:
        resp = lb_client.get("/me/lab/leaderboard?sport=tennis&region=narnia")

        assert resp.status_code == 404

    def test_user_not_found_for_default_region_returns_404(self, lb_client, db) -> None:
        resp = lb_client.get("/me/lab/leaderboard?sport=tennis")

        assert resp.status_code == 404

    def test_area_not_in_region_mapping_returns_404(self, lb_client, db) -> None:
        _seed_user(db, _MY_UID, area=999)
        _seed_region_config(db)

        resp = lb_client.get("/me/lab/leaderboard?sport=tennis")

        assert resp.status_code == 404

    def test_missing_token_returns_401(self) -> None:
        resp = TestClient(app).get("/me/lab/leaderboard?sport=tennis&region=athens")

        assert resp.status_code == 401

    def test_invalid_sport_returns_422(self, lb_client) -> None:
        resp = lb_client.get("/me/lab/leaderboard?sport=badminton&region=athens")

        assert resp.status_code == 422

    def test_sport_required_returns_422(self, lb_client) -> None:
        resp = lb_client.get("/me/lab/leaderboard?region=athens")

        assert resp.status_code == 422
