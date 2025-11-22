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
