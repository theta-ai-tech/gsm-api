"""Integration tests for POST /me (onboarding endpoint).

Requires FIRESTORE_EMULATOR_HOST env var.
A fresh user uid not in seed data is used; the doc is deleted in teardown.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.deps import get_current_user
from app.dependencies.repos import get_tier_config_repo, get_users_repo
from app.main import app
from app.repos.tier_config_repo import TierConfigRepo, _cache  # noqa: F401
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

pytestmark = [pytest.mark.integration]

_TEST_UID = "user_onboarding_integration_test"
_TEST_EMAIL = "onboarding_test@example.com"

_PAYLOAD = {
    "name": "Integration Tester",
    "email": _TEST_EMAIL,
    "sports": ["padel"],
    "levels": {"padel": "intermediate"},
    "area": 1,
}


# ---- Helpers ----


def _seed_tier_config(db: firestore.Client) -> None:
    """Seed config/tiers if not already present (required by TierConfigRepo.get())."""

    doc_ref = db.collection("config").document("tiers")
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set(
            {
                "thresholds": [
                    {
                        "tier": "amateur",
                        "minPts": 1000,
                        "maxPts": 1999,
                        "label": "Amateur",
                        "color": "#8B8B8B",
                    },
                    {
                        "tier": "intermediate",
                        "minPts": 2000,
                        "maxPts": 2999,
                        "label": "Intermediate",
                        "color": "#00A3CC",
                    },
                    {
                        "tier": "advanced",
                        "minPts": 3000,
                        "maxPts": 3999,
                        "label": "Advanced",
                        "color": "#BFFF00",
                    },
                    {
                        "tier": "competitive",
                        "minPts": 4000,
                        "maxPts": None,
                        "label": "Competitive",
                        "color": "#FF6B35",
                    },
                ],
                "version": 1,
                "updatedAt": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }
        )


# ---- Fixtures ----


@pytest.fixture()
def onboarding_client(firestore_client: firestore.Client) -> TestClient:
    import app.repos.tier_config_repo as tcr

    tcr._cache = None  # reset in-process cache so emulator doc is read fresh

    _seed_tier_config(firestore_client)

    app.dependency_overrides[get_users_repo] = lambda: UsersRepo(firestore_client)
    app.dependency_overrides[get_tier_config_repo] = lambda: TierConfigRepo(
        firestore_client
    )
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_TEST_UID, email=_TEST_EMAIL
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _cleanup(firestore_client: firestore.Client):
    yield
    firestore_client.collection("users").document(_TEST_UID).delete()


# ---- Test cases ----


class TestOnboardingIntegration:
    def test_full_round_trip(
        self, onboarding_client: TestClient, firestore_client: firestore.Client
    ) -> None:
        """POST /me creates the user doc; Firestore fields are correct."""
        response = onboarding_client.post("/me", json=_PAYLOAD)

        assert response.status_code == 201
        data = response.json()
        assert data["uid"] == _TEST_UID
        assert data["email"] == _TEST_EMAIL
        assert data["name"] == "Integration Tester"

        # Verify Firestore doc directly
        doc = firestore_client.collection("users").document(_TEST_UID).get()
        assert doc.exists
        raw = doc.to_dict() or {}

        # registrationTier set server-side from intermediate level → intermediate tier
        padel_ranking = raw.get("rankings", {}).get("padel", {})
        assert padel_ranking["registrationTier"] == "intermediate"
        assert padel_ranking["tier"] == "intermediate"
        assert padel_ranking["pts"] == 2000  # tier floor for intermediate

        # playTab defaults
        assert raw["playTab"]["state"] == "DISCOVERY"

    def test_duplicate_returns_409(self, onboarding_client: TestClient) -> None:
        """Re-POST after profile exists → 409 Conflict."""
        first = onboarding_client.post("/me", json=_PAYLOAD)
        assert first.status_code == 201

        second = onboarding_client.post("/me", json=_PAYLOAD)
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"]

    def test_rankings_at_tier_floor(
        self, onboarding_client: TestClient, firestore_client: firestore.Client
    ) -> None:
        """Initial pts equals the tier floor for the mapped tier."""
        payload = {**_PAYLOAD, "levels": {"padel": "beginner"}}
        response = onboarding_client.post("/me", json=payload)
        assert response.status_code == 201

        doc = (
            firestore_client.collection("users").document(_TEST_UID).get().to_dict()
            or {}
        )
        padel_ranking = doc.get("rankings", {}).get("padel", {})

        # beginner → amateur → floor 1000
        assert padel_ranking["registrationTier"] == "amateur"
        assert padel_ranking["pts"] == 1000
