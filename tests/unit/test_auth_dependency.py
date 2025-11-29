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


def test_missing_authorization_header(client):
    resp = client.get("/users/alex")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing Authorization header"


def test_invalid_scheme(client):
    resp = client.get("/users/alex", headers={"Authorization": "Token abc"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid Authorization header format"


def test_invalid_token_rejected(monkeypatch, client):
    def _raise_invalid(token, app=None, check_revoked=True):
        raise deps.firebase_auth.InvalidIdTokenError("bad token")

    monkeypatch.setattr(deps.firebase_auth, "verify_id_token", _raise_invalid)

    resp = client.get("/users/alex", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid Firebase ID token"


def test_audience_or_issuer_mismatch(monkeypatch, client):
    def _return_wrong_project(token, app=None, check_revoked=True):
        return {
            "uid": "alex",
            "aud": "wrong-project",
            "iss": "https://securetoken.google.com/wrong-project",
        }

    monkeypatch.setattr(deps.firebase_auth, "verify_id_token", _return_wrong_project)

    resp = client.get("/users/alex", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Token not issued for this project"


def test_forbidden_when_not_owner(monkeypatch, client):
    def _return_claims(token, app=None, check_revoked=True):
        return {
            "uid": "other-user",
            "aud": "test-project",
            "iss": "https://securetoken.google.com/test-project",
        }

    monkeypatch.setattr(deps.firebase_auth, "verify_id_token", _return_claims)

    resp = client.get("/users/alex", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "You do not own this resource"


def test_successful_auth_returns_user(monkeypatch, client):
    def _return_claims(token, app=None, check_revoked=True):
        return {
            "uid": "alex",
            "email": "alex@example.com",
            "picture": "http://example.com/avatar.png",
            "aud": "test-project",
            "iss": "https://securetoken.google.com/test-project",
            "roles": ["player"],
        }

    monkeypatch.setattr(deps.firebase_auth, "verify_id_token", _return_claims)

    resp = client.get("/users/alex", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    assert resp.json() == {
        "uid": "alex",
        "email": "alex@example.com",
        "picture": "http://example.com/avatar.png",
    }
