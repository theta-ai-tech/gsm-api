"""Unit tests for POST/DELETE /me/device-tokens.

UsersRepo is mocked -- no emulator needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user
from app.dependencies.repos import get_users_repo
from app.main import app
from app.models.enums import PlatformEnum
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

_UID = "user_device_token_test"


@pytest.fixture()
def client_and_repo():
    repo = MagicMock(spec=UsersRepo)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email=None
    )
    app.dependency_overrides[get_users_repo] = lambda: repo
    yield TestClient(app), repo
    app.dependency_overrides = previous


class TestRegisterDeviceToken:
    def test_happy_path_returns_204(self, client_and_repo):
        client, repo = client_and_repo
        response = client.post(
            "/me/device-tokens",
            json={"token": "tok_abc", "platform": "ios", "appVersion": "1.2.3"},
        )

        assert response.status_code == 204
        assert response.content == b""
        repo.upsert_device_token.assert_called_once_with(
            _UID, "tok_abc", PlatformEnum.IOS
        )

    def test_accepts_snake_case_app_version(self, client_and_repo):
        client, repo = client_and_repo
        response = client.post(
            "/me/device-tokens",
            json={"token": "tok_abc", "platform": "android", "app_version": "9.9"},
        )

        assert response.status_code == 204
        repo.upsert_device_token.assert_called_once_with(
            _UID, "tok_abc", PlatformEnum.ANDROID
        )

    def test_invalid_platform_returns_422(self, client_and_repo):
        client, repo = client_and_repo
        response = client.post(
            "/me/device-tokens",
            json={"token": "tok_abc", "platform": "windows"},
        )

        assert response.status_code == 422
        repo.upsert_device_token.assert_not_called()

    def test_empty_token_returns_422(self, client_and_repo):
        client, repo = client_and_repo
        response = client.post(
            "/me/device-tokens",
            json={"token": "", "platform": "ios"},
        )

        assert response.status_code == 422
        repo.upsert_device_token.assert_not_called()

    def test_user_not_found_returns_404(self, client_and_repo):
        client, repo = client_and_repo
        repo.upsert_device_token.side_effect = ValueError(f"user_not_found:{_UID}")

        response = client.post(
            "/me/device-tokens",
            json={"token": "tok_abc", "platform": "ios"},
        )

        assert response.status_code == 404

    def test_other_value_error_returns_400(self, client_and_repo):
        """A non-user_not_found ValueError from the repo maps to 400 (covers the fallback branch)."""
        client, repo = client_and_repo
        repo.upsert_device_token.side_effect = ValueError("something_else")

        response = client.post(
            "/me/device-tokens",
            json={"token": "tok_abc", "platform": "ios"},
        )

        assert response.status_code == 400


class TestDeviceTokenAuth:
    """Auth enforcement with the REAL get_current_user dependency (no override)."""

    def test_post_without_auth_returns_401(self):
        repo = MagicMock(spec=UsersRepo)
        previous = dict(app.dependency_overrides)
        # Only override the repo; let the real get_current_user run -> 401 without a token.
        app.dependency_overrides[get_users_repo] = lambda: repo
        try:
            client = TestClient(app)
            response = client.post(
                "/me/device-tokens",
                json={"token": "tok_abc", "platform": "ios"},
            )
            assert response.status_code == 401
            repo.upsert_device_token.assert_not_called()
        finally:
            app.dependency_overrides = previous

    def test_delete_without_auth_returns_401(self):
        repo = MagicMock(spec=UsersRepo)
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[get_users_repo] = lambda: repo
        try:
            client = TestClient(app)
            response = client.request(
                "DELETE",
                "/me/device-tokens",
                json={"token": "tok_abc"},
            )
            assert response.status_code == 401
            repo.remove_device_token.assert_not_called()
        finally:
            app.dependency_overrides = previous


class TestDeleteDeviceToken:
    def test_happy_path_returns_204(self, client_and_repo):
        client, repo = client_and_repo
        response = client.request(
            "DELETE",
            "/me/device-tokens",
            json={"token": "tok_abc"},
        )

        assert response.status_code == 204
        assert response.content == b""
        repo.remove_device_token.assert_called_once_with(_UID, "tok_abc")

    def test_empty_token_returns_422(self, client_and_repo):
        client, repo = client_and_repo
        response = client.request(
            "DELETE",
            "/me/device-tokens",
            json={"token": ""},
        )

        assert response.status_code == 422
        repo.remove_device_token.assert_not_called()
