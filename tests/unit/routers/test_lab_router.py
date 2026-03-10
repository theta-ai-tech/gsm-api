"""
Unit tests for GET /me/lab/progression.

PointHistoryRepo is mocked — no emulator needed.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user
from app.main import app
from app.models.enums import PointHistoryReasonEnum, SportEnum, TierEnum
from app.models.point_history import PointHistoryEntry
from app.dependencies.repos import get_point_history_repo
from app.routers.lab import _encode_cursor
from app.security import CurrentUser

_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
_UID = "user_test"


def _make_entry(entry_id: str, pts: int = 2000, delta: int = 100) -> PointHistoryEntry:
    return PointHistoryEntry(
        entry_id=entry_id,
        sport=SportEnum.TENNIS,
        pts=pts,
        delta=delta,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match_001",
        opponent_uid="opp_001",
        created_at=_NOW,
        tier_after=TierEnum.INTERMEDIATE,
    )


def _decode_cursor_str(cursor: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(cursor.encode()))


@pytest.fixture
def mock_repo():
    return Mock(spec=["list_entries"])


@pytest.fixture
def mock_user():
    return CurrentUser(uid=_UID, email="test@example.com")


@pytest.fixture
def client(mock_repo, mock_user):
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_point_history_repo] = lambda: mock_repo
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_missing_token_returns_401(self):
        """No dependency override — real auth guard should reject the request."""
        c = TestClient(app)
        resp = c.get("/me/lab/progression?sport=tennis")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestGetProgression:
    def test_returns_entries_for_sport(self, client, mock_repo):
        entries = [_make_entry("e1"), _make_entry("e2")]
        mock_repo.list_entries.return_value = entries

        resp = client.get("/me/lab/progression?sport=tennis")

        assert resp.status_code == 200
        body = resp.json()
        assert body["sport"] == "tennis"
        assert len(body["entries"]) == 2
        assert body["has_more"] is False
        assert body["cursor"] is None

    def test_repo_called_with_correct_args(self, client, mock_repo):
        mock_repo.list_entries.return_value = []

        client.get("/me/lab/progression?sport=padel&limit=10")

        mock_repo.list_entries.assert_called_once_with(
            uid=_UID,
            sport=SportEnum.PADEL,
            limit=11,  # limit+1 for has_more detection
            cursor=None,
        )

    def test_has_more_true_when_extra_entry_returned(self, client, mock_repo):
        # Return limit+1 entries to signal there are more pages.
        entries = [_make_entry(f"e{i}") for i in range(6)]
        mock_repo.list_entries.return_value = entries  # 6 returned for limit=5

        resp = client.get("/me/lab/progression?sport=tennis&limit=5")

        body = resp.json()
        assert body["has_more"] is True
        assert len(body["entries"]) == 5  # extra entry trimmed
        assert body["cursor"] is not None

    def test_cursor_encodes_last_returned_entry(self, client, mock_repo):
        entries = [_make_entry(f"e{i}") for i in range(6)]
        mock_repo.list_entries.return_value = entries

        resp = client.get("/me/lab/progression?sport=tennis&limit=5")

        cursor_data = _decode_cursor_str(resp.json()["cursor"])
        assert cursor_data["entryId"] == "e4"  # index 4 = last of the 5 returned

    def test_cursor_passed_to_repo(self, client, mock_repo):
        entry = _make_entry("e1")
        cursor_str = _encode_cursor(entry)
        mock_repo.list_entries.return_value = []

        client.get(f"/me/lab/progression?sport=tennis&cursor={cursor_str}")

        _, kwargs = mock_repo.list_entries.call_args
        cursor_arg = kwargs["cursor"]
        assert cursor_arg["entryId"] == "e1"
        assert isinstance(cursor_arg["createdAt"], datetime)

    def test_empty_result(self, client, mock_repo):
        mock_repo.list_entries.return_value = []

        resp = client.get("/me/lab/progression?sport=tennis")

        body = resp.json()
        assert body["entries"] == []
        assert body["has_more"] is False
        assert body["cursor"] is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_sport_returns_422(self, client, mock_repo):
        resp = client.get("/me/lab/progression?sport=badminton")
        assert resp.status_code == 422

    def test_sport_is_required(self, client, mock_repo):
        resp = client.get("/me/lab/progression")
        assert resp.status_code == 422

    def test_limit_above_max_returns_422(self, client, mock_repo):
        resp = client.get("/me/lab/progression?sport=tennis&limit=201")
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, client, mock_repo):
        resp = client.get("/me/lab/progression?sport=tennis&limit=0")
        assert resp.status_code == 422

    def test_invalid_cursor_returns_400(self, client, mock_repo):
        resp = client.get("/me/lab/progression?sport=tennis&cursor=notvalidbase64!!!")
        assert resp.status_code == 400
