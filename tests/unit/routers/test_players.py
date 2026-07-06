"""Unit tests for GET /players.

The users repo is mocked -- no emulator needed.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_users_repo
from app.deps import get_current_user
from app.main import app
from app.security import CurrentUser

_UID = "user_ignatios"


@pytest.fixture()
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email="ignatios@gsm.local"
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def mock_users_repo():
    repo = Mock()
    repo.search_by_name_prefix.return_value = []
    app.dependency_overrides[get_users_repo] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_users_repo, None)


@pytest.fixture()
def client(_override_auth, mock_users_repo):
    return TestClient(app)


def _user_doc(uid: str, name: str, padel_pts: int | None = None) -> dict:
    doc: dict = {"uid": uid, "name": name, "profileUrl": f"https://img/{uid}.png"}
    if padel_pts is not None:
        doc["rankings"] = {"padel": {"pts": padel_pts}}
    return doc


class TestSearchPlayersHappyPath:
    def test_prefix_match_returns_players(
        self, client: TestClient, mock_users_repo: Mock
    ):
        mock_users_repo.search_by_name_prefix.return_value = [
            _user_doc("user_maria", "Maria Dimas"),
            _user_doc("user_marios", "Marios Vassiliou"),
        ]
        resp = client.get("/players", params={"search": "mar"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["players"]) == 2
        assert body["players"][0]["uid"] == "user_maria"
        assert body["players"][0]["display_name"] == "Maria Dimas"
        assert body["players"][0]["profile_url"] == "https://img/user_maria.png"
        assert body["players"][0]["pts"] is None

    def test_excludes_caller_via_repo(self, client: TestClient, mock_users_repo: Mock):
        client.get("/players", params={"search": "mar"})
        mock_users_repo.search_by_name_prefix.assert_called_once()
        kwargs = mock_users_repo.search_by_name_prefix.call_args.kwargs
        assert kwargs["exclude_uid"] == _UID

    def test_limit_forwarded_to_repo(self, client: TestClient, mock_users_repo: Mock):
        client.get("/players", params={"search": "mar", "limit": 5})
        kwargs = mock_users_repo.search_by_name_prefix.call_args.kwargs
        assert kwargs["limit"] == 5

    def test_default_limit_is_ten(self, client: TestClient, mock_users_repo: Mock):
        client.get("/players", params={"search": "mar"})
        kwargs = mock_users_repo.search_by_name_prefix.call_args.kwargs
        assert kwargs["limit"] == 10

    def test_pts_populated_when_sport_given(
        self, client: TestClient, mock_users_repo: Mock
    ):
        mock_users_repo.search_by_name_prefix.return_value = [
            _user_doc("user_maria", "Maria Dimas", padel_pts=1200),
        ]
        resp = client.get("/players", params={"search": "mar", "sport": "padel"})
        assert resp.status_code == 200
        assert resp.json()["players"][0]["pts"] == 1200

    def test_pts_none_when_sport_missing_ranking(
        self, client: TestClient, mock_users_repo: Mock
    ):
        mock_users_repo.search_by_name_prefix.return_value = [
            _user_doc("user_maria", "Maria Dimas"),
        ]
        resp = client.get("/players", params={"search": "mar", "sport": "padel"})
        assert resp.status_code == 200
        assert resp.json()["players"][0]["pts"] is None

    def test_pts_ignored_when_no_sport(self, client: TestClient, mock_users_repo: Mock):
        mock_users_repo.search_by_name_prefix.return_value = [
            _user_doc("user_maria", "Maria Dimas", padel_pts=1200),
        ]
        resp = client.get("/players", params={"search": "mar"})
        assert resp.status_code == 200
        assert resp.json()["players"][0]["pts"] is None

    def test_empty_results(self, client: TestClient):
        resp = client.get("/players", params={"search": "zzz"})
        assert resp.status_code == 200
        assert resp.json()["players"] == []


class TestSearchPlayersValidation:
    def test_missing_search_returns_422(self, client: TestClient):
        resp = client.get("/players")
        assert resp.status_code == 422

    def test_empty_search_returns_422(self, client: TestClient):
        resp = client.get("/players", params={"search": ""})
        assert resp.status_code == 422

    def test_limit_too_high_returns_422(self, client: TestClient):
        resp = client.get("/players", params={"search": "mar", "limit": 21})
        assert resp.status_code == 422

    def test_limit_too_low_returns_422(self, client: TestClient):
        resp = client.get("/players", params={"search": "mar", "limit": 0})
        assert resp.status_code == 422

    def test_invalid_sport_returns_422(self, client: TestClient):
        resp = client.get("/players", params={"search": "mar", "sport": "chess"})
        assert resp.status_code == 422


class TestSearchPlayersAuth:
    def test_no_auth_returns_401(self):
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/players", params={"search": "mar"})
        assert resp.status_code == 401
