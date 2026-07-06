"""Integration tests for PATCH /me/clubhouse/profile (issue #364).

Drives the real endpoint via TestClient against the Firestore emulator,
overriding the auth + repo dependencies to emulator-backed instances.

Verifies:
- PATCH-then-GET round-trip (rename + area change) with untouched fields
- levels merge is per-sport and never touches the rankings map
- unknown area is rejected against the seeded region config
- a rename updates nameLower so player prefix search resolves the new name

Requires: FIRESTORE_EMULATOR_HOST env var set (e.g. via `make emu-all`)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.repos.region_config_repo as region_config_module
from app.dependencies.repos import get_region_config_repo, get_users_repo
from app.deps import get_current_user
from app.main import app
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.integration]

_NOW = datetime.now(timezone.utc)
_UID = "patch_user_364"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_region_cache():
    region_config_module._cache = None
    region_config_module._cache_ts = 0.0
    yield
    region_config_module._cache = None
    region_config_module._cache_ts = 0.0


@pytest.fixture(autouse=True)
def _cleanup_regions(db):
    yield
    db.collection("config").document("regions").delete()


def _seed_region_config(db) -> None:
    db.collection("config").document("regions").set(
        {"mapping": {"101": "athens", "202": "thessaloniki"}, "version": 1}
    )


def _seed_user(db) -> None:
    db.collection("users").document(_UID).set(
        {
            "uid": _UID,
            "name": "Original Name",
            "nameLower": "original name",
            "email": "patch_user_364@test.com",
            "profileUrl": None,
            "isPro": False,
            "phone": None,
            "rankings": {
                "tennis": {
                    "sport": "tennis",
                    "pts": 1500,
                    "tier": "amateur",
                    "registrationTier": "amateur",
                    "currentStreak": 2,
                    "bestStreak": 4,
                    "globalRanking": None,
                    "lastUpdated": None,
                    "personalBest": 1600,
                }
            },
            "preferences": {
                "area": 101,
                "levels": {"tennis": "advanced", "padel": "beginner"},
                "sports": ["tennis", "padel"],
                "feedOptOut": False,
            },
            "leaguesActive": [],
            "leaguesCompleted": [],
            "upcomingMatches": [],
            "completedMatches": [],
            "journalRecent": [],
            "cursors": None,
            "northStarGoal": None,
            "skillDna": {},
            "deviceTokens": [],
            "playTab": {
                "state": "DISCOVERY",
                "activeBroadcastId": None,
                "activeMatchId": None,
                "activeOutgoingOfferId": None,
                "pendingIncomingOfferIds": [],
                "updatedAt": _NOW,
            },
        }
    )


@pytest.fixture
def client(db):
    app.dependency_overrides[get_users_repo] = lambda: UsersRepo(db)
    app.dependency_overrides[get_region_config_repo] = lambda: RegionConfigRepo(db)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email="patch_user_364@test.com"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _raw(db) -> dict:
    return db.collection("users").document(_UID).get().to_dict() or {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPatchProfileRoundTrip:
    def test_rename_and_area_reflected_in_get(self, db, client):
        _seed_region_config(db)
        _seed_user(db)

        patch_resp = client.patch(
            "/me/clubhouse/profile",
            json={"display_name": "Brand New", "area": 202},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["display_name"] == "Brand New"

        get_resp = client.get("/me/clubhouse/profile")
        assert get_resp.status_code == 200
        assert get_resp.json()["display_name"] == "Brand New"

        raw = _raw(db)
        assert raw["name"] == "Brand New"
        assert raw["nameLower"] == "brand new"
        assert raw["preferences"]["area"] == 202
        # untouched fields
        assert raw["email"] == "patch_user_364@test.com"
        assert raw["preferences"]["sports"] == ["tennis", "padel"]


class TestLevelsMergeAndRankingsUntouched:
    def test_levels_merge_preserves_other_sport_and_rankings(self, db, client):
        _seed_region_config(db)
        _seed_user(db)
        rankings_before = _raw(db)["rankings"]

        resp = client.patch(
            "/me/clubhouse/profile",
            json={"levels": {"padel": "intermediate"}},
        )
        assert resp.status_code == 200

        raw = _raw(db)
        # merge: padel updated, tennis level untouched
        assert raw["preferences"]["levels"]["padel"] == "intermediate"
        assert raw["preferences"]["levels"]["tennis"] == "advanced"
        # rankings byte-identical
        assert raw["rankings"] == rankings_before


class TestUnknownArea:
    def test_unknown_area_returns_422(self, db, client):
        _seed_region_config(db)
        _seed_user(db)

        resp = client.patch("/me/clubhouse/profile", json={"area": 999})
        assert resp.status_code == 422
        # doc untouched
        assert _raw(db)["preferences"]["area"] == 101


class TestRenameVisibleToSearch:
    def test_rename_updates_name_lower_for_prefix_search(self, db, client):
        _seed_region_config(db)
        _seed_user(db)

        resp = client.patch(
            "/me/clubhouse/profile", json={"display_name": "Zephyr Quinn"}
        )
        assert resp.status_code == 200

        repo = UsersRepo(db)
        results = repo.search_by_name_prefix("zephyr", limit=10)
        uids = [r["uid"] for r in results]
        assert _UID in uids
