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


@pytest.fixture
def mock_verify(monkeypatch):
    """Helper to swap firebase_auth.verify_id_token for test cases."""

    def _set(*, returns=None, exc: Exception | None = None):
        if exc:

            def _raise(*_args, **_kwargs):
                raise exc

            monkeypatch.setattr(deps.firebase_auth, "verify_id_token", _raise)
        else:

            def _return(*_args, **_kwargs):
                return returns

            monkeypatch.setattr(deps.firebase_auth, "verify_id_token", _return)

    return _set


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    "headers,verify_kwargs,expected_status",
    [
        pytest.param(None, {}, 401, id="no_token"),
        pytest.param(
            bearer("not-a-token"),
            {"exc": deps.firebase_auth.InvalidIdTokenError("bad")},
            401,
            id="invalid_token",
        ),
        pytest.param(
            bearer("good"),
            {
                "returns": {
                    "uid": "other-user",
                    "aud": "test-project",
                    "iss": "https://securetoken.google.com/test-project",
                }
            },
            403,
            id="wrong_uid",
        ),
    ],
)
def test_protected_route_authz_failures(
    client, mock_verify, headers, verify_kwargs, expected_status
):
    if verify_kwargs:
        mock_verify(**verify_kwargs)

    resp = client.get("/users/alex", headers=headers or {})
    assert resp.status_code == expected_status


def test_protected_route_valid_token_correct_uid_returns_200(client, mock_verify):
    mock_verify(
        returns={
            "uid": "alex",
            "email": "alex@example.com",
            "iss": "https://securetoken.google.com/test-project",
            "aud": "test-project",
            "roles": ["player"],
        }
    )

    resp = client.get("/users/alex", headers=bearer("good"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["uid"] == "alex"
    assert body["email"] == "alex@example.com"
