"""Unit tests for POST /me (onboarding endpoint).

Repos and service are mocked -- no emulator needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user
from app.main import app
from app.models.common import (
    PerSportLevels,
    PerSportRankings,
    SportRanking,
    UserPreferences,
)
from app.models.enums import LevelEnum, SportEnum, TierEnum
from app.models.user import PrivateUserProfile
from app.routers.onboarding import get_onboarding_service
from app.security import CurrentUser
from app.services.onboarding_service import OnboardingConfigError, OnboardingService

# ---- Helpers ----

_UID = "user_onboarding_test"
_EMAIL_TOKEN = "token@example.com"
_EMAIL_BODY = "body@example.com"

_HAPPY_PAYLOAD = {
    "name": "Test User",
    "sports": ["padel"],
    "levels": {"padel": "intermediate"},
    "area": 1,
}


def _make_profile(uid: str = _UID, email: str = _EMAIL_TOKEN) -> PrivateUserProfile:
    """Build a minimal PrivateUserProfile for mock return values."""
    ranking = SportRanking(
        sport=SportEnum.PADEL,
        pts=2000,
        tier=TierEnum.INTERMEDIATE,
        registration_tier=TierEnum.INTERMEDIATE,
    )
    return PrivateUserProfile(
        uid=uid,
        name="Test User",
        email=email,
        profile_url=None,
        is_pro=False,
        rankings=PerSportRankings(padel=ranking),
        leagues_active=[],
        leagues_completed=[],
        skill_dna=None,
        preferences=UserPreferences(
            area=1,
            levels=PerSportLevels(padel=LevelEnum.INTERMEDIATE),
            sports=[SportEnum.PADEL],
        ),
        upcoming_matches=[],
        completed_matches=[],
        journal_recent=[],
        cursors=None,
        north_star_goal=None,
    )


def _mock_service(profile: PrivateUserProfile | None = None) -> OnboardingService:
    svc = MagicMock(spec=OnboardingService)
    svc.register_me.return_value = profile or _make_profile()
    return svc


# ---- Fixtures ----


@pytest.fixture()
def client_with_email():
    """Client where token has email."""
    svc = _mock_service()
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email=_EMAIL_TOKEN
    )
    app.dependency_overrides[get_onboarding_service] = lambda: svc
    yield TestClient(app), svc
    app.dependency_overrides = previous


@pytest.fixture()
def client_no_email():
    """Client where token has NO email."""
    svc = _mock_service(_make_profile(email=_EMAIL_BODY))
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email=None
    )
    app.dependency_overrides[get_onboarding_service] = lambda: svc
    yield TestClient(app), svc
    app.dependency_overrides = previous


# ---- Test cases ----


class TestRegisterMe:
    def test_happy_path_returns_201(self, client_with_email):
        client, svc = client_with_email
        response = client.post("/me", json=_HAPPY_PAYLOAD)

        assert response.status_code == 201
        data = response.json()
        assert data["uid"] == _UID
        assert data["email"] == _EMAIL_TOKEN
        svc.register_me.assert_called_once()

    def test_duplicate_returns_409(self, client_with_email):
        client, svc = client_with_email
        svc.register_me.side_effect = ValueError("already_registered")

        response = client.post("/me", json=_HAPPY_PAYLOAD)

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_tier_config_missing_returns_500(self, client_with_email):
        """OnboardingConfigError (e.g. config/tiers missing) → 500, not 400."""
        client, svc = client_with_email
        svc.register_me.side_effect = OnboardingConfigError(
            "Tier config not found in Firestore (config/tiers)"
        )

        response = client.post("/me", json=_HAPPY_PAYLOAD)

        assert response.status_code == 500
        assert "Tier config not found" in response.json()["detail"]

    def test_email_from_token_no_body_email(self, client_with_email):
        """Token email is used; request body has no email field."""
        client, svc = client_with_email
        payload = {**_HAPPY_PAYLOAD}  # no 'email' key
        response = client.post("/me", json=payload)

        assert response.status_code == 201
        call_kwargs = svc.register_me.call_args
        assert call_kwargs.kwargs["token_email"] == _EMAIL_TOKEN

    def test_email_from_body_when_token_has_none(self, client_no_email):
        """Body email is accepted when token lacks email."""
        client, svc = client_no_email
        payload = {**_HAPPY_PAYLOAD, "email": _EMAIL_BODY}
        response = client.post("/me", json=payload)

        assert response.status_code == 201
        call_kwargs = svc.register_me.call_args
        assert call_kwargs.kwargs["token_email"] is None

    def test_no_email_anywhere_returns_422(self, client_no_email):
        """Neither token nor body has email → service raises email_required → 422."""
        client, svc = client_no_email
        svc.register_me.side_effect = ValueError("email_required")

        response = client.post("/me", json=_HAPPY_PAYLOAD)

        assert response.status_code == 422

    def test_missing_level_for_declared_sport_returns_422(self, client_with_email):
        """Pydantic validator rejects request when a sport has no level supplied."""
        client, _ = client_with_email
        payload = {
            "name": "Test",
            "sports": ["padel", "tennis"],
            "levels": {"padel": "intermediate"},  # tennis missing
            "area": 1,
        }
        response = client.post("/me", json=payload)

        assert response.status_code == 422

    def test_empty_sports_list_returns_422(self, client_with_email):
        """sports=[] is rejected by Field(min_length=1) at the model layer."""
        client, _ = client_with_email
        payload = {
            "name": "Test",
            "sports": [],
            "levels": {},
            "area": 1,
        }
        response = client.post("/me", json=payload)
        assert response.status_code == 422

    def test_invalid_profile_url_returns_422(self, client_with_email):
        """profile_url that is not a valid URL is rejected by Pydantic (HttpUrl)."""
        client, _ = client_with_email
        payload = {**_HAPPY_PAYLOAD, "profile_url": "not-a-url"}
        response = client.post("/me", json=payload)
        assert response.status_code == 422
