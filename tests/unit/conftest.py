import os

# Ensure required env is present before app import (app.main calls get_settings at import time)
os.environ.setdefault("FIREBASE_PROJECT_ID", "gsm-dev-f70d0")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "gsm-dev-f70d0")

import pytest
from fastapi.testclient import TestClient

from app.main import app


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
