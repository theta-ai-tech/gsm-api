"""Unit tests for DELETE /me/account (repos + auth admin mocked, no emulator)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from firebase_admin import auth as firebase_auth  # type: ignore[import-untyped]

from app.dependencies.repos import (
    get_auth_admin,
    get_journal_repo,
    get_point_history_repo,
    get_users_repo,
)
from app.deps import get_current_user
from app.main import app
from app.repos.journal_repo import JournalRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.auth_admin import AuthAdmin

_UID = "user_delete_me"


@pytest.fixture()
def client_and_mocks():
    users_repo = MagicMock(spec=UsersRepo)
    journal_repo = MagicMock(spec=JournalRepo)
    point_history_repo = MagicMock(spec=PointHistoryRepo)
    auth_admin = MagicMock(spec=AuthAdmin)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email=None
    )
    app.dependency_overrides[get_users_repo] = lambda: users_repo
    app.dependency_overrides[get_journal_repo] = lambda: journal_repo
    app.dependency_overrides[get_point_history_repo] = lambda: point_history_repo
    app.dependency_overrides[get_auth_admin] = lambda: auth_admin
    yield TestClient(app), users_repo, journal_repo, point_history_repo, auth_admin
    app.dependency_overrides = previous


class TestDeleteAccount:
    def test_happy_path_returns_204_and_runs_full_sequence(self, client_and_mocks):
        client, users_repo, journal_repo, point_history_repo, auth_admin = (
            client_and_mocks
        )

        response = client.request("DELETE", "/me/account")

        assert response.status_code == 204
        assert response.content == b""
        auth_admin.revoke_refresh_tokens.assert_called_once_with(_UID)
        auth_admin.delete_user.assert_called_once_with(_UID)
        journal_repo.delete_all_for_user.assert_called_once_with(_UID)
        point_history_repo.delete_all_for_user.assert_called_once_with(_UID)
        users_repo.anonymize.assert_called_once_with(_UID)

    def test_auth_user_already_gone_is_idempotent(self, client_and_mocks):
        client, users_repo, _journal_repo, _ph_repo, auth_admin = client_and_mocks
        auth_admin.delete_user.side_effect = firebase_auth.UserNotFoundError("gone")

        response = client.request("DELETE", "/me/account")

        assert response.status_code == 204
        # Data cleanup still runs even when the Auth user was already deleted.
        users_repo.anonymize.assert_called_once_with(_UID)

    def test_unexpected_auth_failure_returns_500_and_skips_cleanup(
        self, client_and_mocks
    ):
        client, users_repo, journal_repo, point_history_repo, auth_admin = (
            client_and_mocks
        )
        auth_admin.delete_user.side_effect = RuntimeError("firebase down")
        # The global exception handler maps unhandled errors to 500; disable the
        # TestClient re-raise so we observe the HTTP response the client would get.
        client = TestClient(app, raise_server_exceptions=False)

        response = client.request("DELETE", "/me/account")

        assert response.status_code == 500
        # Cleanup must not run if identity deletion failed unexpectedly.
        journal_repo.delete_all_for_user.assert_not_called()
        point_history_repo.delete_all_for_user.assert_not_called()
        users_repo.anonymize.assert_not_called()


class TestDeleteAccountAuth:
    def test_without_auth_returns_401(self):
        previous = dict(app.dependency_overrides)
        users_repo = MagicMock(spec=UsersRepo)
        app.dependency_overrides[get_users_repo] = lambda: users_repo
        try:
            client = TestClient(app)
            response = client.request("DELETE", "/me/account")
            assert response.status_code == 401
            users_repo.anonymize.assert_not_called()
        finally:
            app.dependency_overrides = previous
