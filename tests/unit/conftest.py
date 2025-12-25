import os

import pytest
from fastapi.testclient import TestClient

# Ensure required env is present before app import (app.main calls get_settings at import time)
os.environ.setdefault("FIREBASE_PROJECT_ID", "gsm-dev-f70d0")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "gsm-dev-f70d0")

from app.main import app
from app.dependencies.repos import get_users_repo
from app.models import (
    PerSportLevels,
    PerSportRankings,
    PrivateUserProfile,
    UserPreferences,
)


class _StubUsersRepo:
    def get_private_profile(self, uid: str):
        return PrivateUserProfile(
            uid=uid,
            name=uid,
            email=f"{uid}@example.com",
            phone=None,
            profile_url=None,
            rankings=PerSportRankings(),
            leagues_active=[],
            leagues_completed=[],
            preferences=UserPreferences(area=1, levels=PerSportLevels(), sports=[]),
            upcoming_matches=[],
            completed_matches=[],
            journal_recent=[],
            cursors=None,
        )

    def get_public_profile(self, uid: str):
        return self.get_private_profile(uid)


app.dependency_overrides[get_users_repo] = lambda: _StubUsersRepo()


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture
def sample_user():
    return {
        "name": "Alex Padel",
        "email": "alex@example.com",
        "preferences": {"area": 42, "sports": ["padel"]},
    }
