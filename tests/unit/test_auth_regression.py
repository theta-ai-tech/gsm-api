import pytest
from fastapi.testclient import TestClient

from app import deps
from app.main import app


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    deps.get_settings.cache_clear()
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-project")
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    yield
    deps.get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_protected_route_no_token_returns_401(client):
    resp = client.get("/users/alex")
    assert resp.status_code == 401


def test_protected_route_invalid_token_returns_401(monkeypatch, client):
    def _raise_invalid(token, app=None, check_revoked=True):
        raise deps.firebase_auth.InvalidIdTokenError("bad token")

    monkeypatch.setattr(deps.firebase_auth, "verify_id_token", _raise_invalid)

    resp = client.get("/users/alex", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401


def test_protected_route_valid_token_wrong_uid_returns_403(monkeypatch, client):
    def _return_other_user(token, app=None, check_revoked=True):
        return {
            "uid": "other-user",
            "aud": "test-project",
            "iss": "https://securetoken.google.com/test-project",
        }

    monkeypatch.setattr(deps.firebase_auth, "verify_id_token", _return_other_user)

    resp = client.get("/users/alex", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 403


def test_protected_route_valid_token_correct_uid_returns_200(monkeypatch, client):
    def _return_matching_user(token, app=None, check_revoked=True):
        return {
            "uid": "alex",
            "email": "alex@example.com",
            "iss": "https://securetoken.google.com/test-project",
            "aud": "test-project",
            "roles": ["player"],
        }

    monkeypatch.setattr(deps.firebase_auth, "verify_id_token", _return_matching_user)

    resp = client.get("/users/alex", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["uid"] == "alex"
    assert body["email"] == "alex@example.com"
