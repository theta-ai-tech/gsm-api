"""Integration tests for POST/DELETE /me/device-tokens (emulator-backed).

Requires FIRESTORE_EMULATOR_HOST env var.
A fresh user uid not in seed data is created; the autouse cleanup wipes the users collection.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.deps import get_current_user
from app.dependencies.repos import get_users_repo
from app.main import app
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

pytestmark = [pytest.mark.integration]

_TEST_UID = "user_device_token_integration"
_TEST_EMAIL = "device_token_test@example.com"


@pytest.fixture()
def device_token_client(firestore_client: firestore.Client) -> TestClient:
    firestore_client.collection("users").document(_TEST_UID).set(
        {"uid": _TEST_UID, "name": "Token Tester", "email": _TEST_EMAIL}
    )
    app.dependency_overrides[get_users_repo] = lambda: UsersRepo(firestore_client)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_TEST_UID, email=_TEST_EMAIL
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _read_tokens(db: firestore.Client) -> list[dict]:
    doc = db.collection("users").document(_TEST_UID).get().to_dict() or {}
    return doc.get("deviceTokens") or []


class TestDeviceTokensIntegration:
    def test_register_creates_token(
        self, device_token_client: TestClient, firestore_client: firestore.Client
    ) -> None:
        response = device_token_client.post(
            "/me/device-tokens",
            json={"token": "tok_1", "platform": "ios", "appVersion": "1.0.0"},
        )
        assert response.status_code == 204

        tokens = _read_tokens(firestore_client)
        assert len(tokens) == 1
        assert tokens[0]["token"] == "tok_1"
        assert tokens[0]["platform"] == "ios"
        assert "lastSeenAt" in tokens[0]

    def test_reregister_is_idempotent_and_refreshes_last_seen(
        self, device_token_client: TestClient, firestore_client: firestore.Client
    ) -> None:
        first = device_token_client.post(
            "/me/device-tokens",
            json={"token": "tok_dup", "platform": "android"},
        )
        assert first.status_code == 204
        before = _read_tokens(firestore_client)
        assert len(before) == 1
        first_last_seen = before[0]["lastSeenAt"]

        second = device_token_client.post(
            "/me/device-tokens",
            json={"token": "tok_dup", "platform": "android"},
        )
        assert second.status_code == 204

        after = _read_tokens(firestore_client)
        assert len(after) == 1  # no duplicate
        assert after[0]["lastSeenAt"] >= first_last_seen  # refreshed

    def test_delete_removes_token(
        self, device_token_client: TestClient, firestore_client: firestore.Client
    ) -> None:
        device_token_client.post(
            "/me/device-tokens",
            json={"token": "tok_del", "platform": "ios"},
        )
        assert len(_read_tokens(firestore_client)) == 1

        response = device_token_client.request(
            "DELETE",
            "/me/device-tokens",
            json={"token": "tok_del"},
        )
        assert response.status_code == 204
        assert _read_tokens(firestore_client) == []

    def test_register_unknown_user_returns_404(
        self, firestore_client: firestore.Client
    ) -> None:
        app.dependency_overrides[get_users_repo] = lambda: UsersRepo(firestore_client)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid="user_does_not_exist", email=None
        )
        try:
            client = TestClient(app)
            response = client.post(
                "/me/device-tokens",
                json={"token": "tok_x", "platform": "ios"},
            )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
