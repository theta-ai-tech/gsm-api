import base64
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user
from app.main import app
from app.models.enums import (
    JournalEntryTypeEnum,
    JournalVisibilityEnum,
)
from app.models.journal import (
    CreateJournalEntryResponse,
    JournalEntry,
)
from app.models.stats import NorthStarGoal, UserStats, WeeklyActivity
from app.routers.improve import get_journal_service
from app.security import CurrentUser
from app.services.journal_service import JournalService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(entry_id: str = "e1") -> JournalEntry:
    return JournalEntry(
        entry_id=entry_id,
        uid="test_user",
        created_at=datetime.now(timezone.utc),
        title="Test Entry",
        body="Body text",
        visibility=JournalVisibilityEnum.PRIVATE,
        entry_type=JournalEntryTypeEnum.MATCH,
    )


def _make_stats() -> UserStats:
    return UserStats(
        uid="test_user",
        weekly_activity=WeeklyActivity(),
        total_matches=5,
        total_wins=3,
        total_training_sessions=2,
        current_streak=1,
    )


def _encode_cursor(created_at: datetime, entry_id: str) -> str:
    raw = {"createdAt": created_at.isoformat(), "entryId": entry_id}
    return base64.urlsafe_b64encode(json.dumps(raw).encode()).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_journal_service():
    return Mock(spec=JournalService)


@pytest.fixture
def mock_current_user():
    return CurrentUser(uid="test_user", email="test@example.com")


@pytest.fixture
def client(mock_journal_service, mock_current_user):
    """TestClient with mocked JournalService and auth dependencies."""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_journal_service] = lambda: mock_journal_service
    app.dependency_overrides[get_current_user] = lambda: mock_current_user
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# GET /me/journal
# ---------------------------------------------------------------------------


class TestListJournalEntries:
    def test_list_entries_returns_200_with_entries(self, client, mock_journal_service):
        """Returns 200 with entries list; no next_cursor when fewer than limit."""
        entries = [_make_entry("e1"), _make_entry("e2")]
        mock_journal_service.list_entries.return_value = entries

        response = client.get("/me/journal")

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 2
        assert data["entries"][0]["entry_id"] == "e1"
        assert data["next_cursor"] is None

    def test_list_entries_returns_200_empty(self, client, mock_journal_service):
        """Returns 200 with an empty entries list when the user has no entries."""
        mock_journal_service.list_entries.return_value = []

        response = client.get("/me/journal")

        assert response.status_code == 200
        data = response.json()
        assert data["entries"] == []
        assert data["next_cursor"] is None

    def test_list_entries_with_limit_sets_next_cursor(
        self, client, mock_journal_service
    ):
        """When entries == limit, response includes a next_cursor token."""
        entries = [_make_entry("e1"), _make_entry("e2")]
        mock_journal_service.list_entries.return_value = entries

        response = client.get("/me/journal?limit=2")

        assert response.status_code == 200
        data = response.json()
        assert data["next_cursor"] is not None
        mock_journal_service.list_entries.assert_called_once_with(
            "test_user",
            limit=2,
            cursor=None,
        )

    def test_list_entries_with_cursor_decodes_and_passes_to_service(
        self, client, mock_journal_service
    ):
        """Valid cursor query param is decoded before service call."""
        mock_journal_service.list_entries.return_value = []
        created_at = datetime.now(timezone.utc)
        cursor = _encode_cursor(created_at, "e9")

        response = client.get(f"/me/journal?cursor={cursor}")

        assert response.status_code == 200
        called_cursor = mock_journal_service.list_entries.call_args.kwargs["cursor"]
        assert called_cursor["entryId"] == "e9"
        assert called_cursor["createdAt"] == created_at

    def test_list_entries_invalid_cursor_returns_400(
        self, client, mock_journal_service
    ):
        """Malformed cursor returns 400 and does not call service."""
        response = client.get("/me/journal?cursor=not-base64")

        assert response.status_code == 400
        mock_journal_service.list_entries.assert_not_called()


# ---------------------------------------------------------------------------
# POST /me/journal
# ---------------------------------------------------------------------------


class TestCreateJournalEntry:
    def test_create_match_entry_returns_201(self, client, mock_journal_service):
        """Valid match entry request returns 201 with entry_id."""
        now = datetime.now(timezone.utc)
        mock_journal_service.create_entry.return_value = CreateJournalEntryResponse(
            entry_id="new_entry",
            created_at=now,
        )

        payload = {
            "entry_type": "match",
            "title": "My match",
            "body": "Played well today",
            "sport": "tennis",
        }
        response = client.post("/me/journal", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["entry_id"] == "new_entry"
        mock_journal_service.create_entry.assert_called_once()

    def test_create_training_entry_returns_201(self, client, mock_journal_service):
        """Valid training entry with duration and focus returns 201."""
        now = datetime.now(timezone.utc)
        mock_journal_service.create_entry.return_value = CreateJournalEntryResponse(
            entry_id="train_entry",
            created_at=now,
        )

        payload = {
            "entry_type": "training",
            "title": "Serve drill",
            "body": "Worked on kick serve",
            "duration_minutes": 45,
            "training_focus": ["serve"],
            "sport": "tennis",
        }
        response = client.post("/me/journal", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["entry_id"] == "train_entry"

    def test_create_entry_missing_required_fields_returns_422(
        self, client, mock_journal_service
    ):
        """Missing entry_type returns 422 Unprocessable Entity."""
        payload = {
            "title": "No type",
            "body": "Missing entry_type field",
        }
        response = client.post("/me/journal", json=payload)

        assert response.status_code == 422
        mock_journal_service.create_entry.assert_not_called()

    def test_create_entry_invalid_enum_returns_422(self, client, mock_journal_service):
        """Invalid entry_type enum value returns 422."""
        payload = {
            "entry_type": "invalid_type",
            "title": "Bad entry",
        }
        response = client.post("/me/journal", json=payload)

        assert response.status_code == 422
        mock_journal_service.create_entry.assert_not_called()

    def test_create_training_without_duration_returns_422(
        self, client, mock_journal_service
    ):
        """Model validation error for training entries without duration."""
        payload = {
            "entry_type": "training",
            "title": "No duration",
            "sport": "tennis",
        }
        response = client.post("/me/journal", json=payload)

        assert response.status_code == 422
        mock_journal_service.create_entry.assert_not_called()

    def test_create_entry_not_found_maps_to_404(self, client, mock_journal_service):
        """Service ValueError containing 'not found' maps to 404."""
        mock_journal_service.create_entry.side_effect = ValueError("User not found")

        payload = {
            "entry_type": "match",
            "title": "My match",
        }
        response = client.post("/me/journal", json=payload)

        assert response.status_code == 404

    def test_create_entry_conflict_maps_to_409(self, client, mock_journal_service):
        """Service ValueError without 'not found' maps to 409."""
        mock_journal_service.create_entry.side_effect = ValueError(
            "Duplicate journal entry"
        )

        payload = {
            "entry_type": "match",
            "title": "My match",
        }
        response = client.post("/me/journal", json=payload)

        assert response.status_code == 409


# ---------------------------------------------------------------------------
# PATCH /me/journal/{entry_id}
# ---------------------------------------------------------------------------


class TestUpdateJournalEntry:
    def test_update_entry_returns_200(self, client, mock_journal_service):
        """Valid reflection update returns 200 with entry_id."""
        mock_journal_service.update_entry.return_value = None

        payload = {
            "reflection": {
                "went_well": ["first_serve"],
                "went_wrong": ["double_faults"],
            }
        }
        response = client.patch("/me/journal/e1", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["entry_id"] == "e1"
        assert data["updated"] is True

    def test_update_entry_not_found_returns_404(self, client, mock_journal_service):
        """Service raises ValueError('not found') → 404."""
        mock_journal_service.update_entry.side_effect = ValueError(
            "Journal entry 'missing' not found"
        )

        response = client.patch("/me/journal/missing", json={"tags": ["x"]})

        assert response.status_code == 404

    def test_update_entry_wrong_owner_returns_403(self, client, mock_journal_service):
        """Service raises ownership error mapped to 403."""
        mock_journal_service.update_entry.side_effect = ValueError(
            "Entry does not belong to this user"
        )

        response = client.patch("/me/journal/e1", json={"tags": ["x"]})

        assert response.status_code == 403

    def test_update_entry_conflict_returns_409(self, client, mock_journal_service):
        """Other service ValueError cases map to 409."""
        mock_journal_service.update_entry.side_effect = ValueError(
            "Cannot patch archived entry"
        )

        response = client.patch("/me/journal/e1", json={"tags": ["x"]})

        assert response.status_code == 409


# ---------------------------------------------------------------------------
# GET /me/stats
# ---------------------------------------------------------------------------


class TestGetDashboardStats:
    def test_get_stats_returns_200(self, client, mock_journal_service):
        """Returns 200 with UserStats payload."""
        mock_journal_service.get_dashboard_stats.return_value = _make_stats()

        response = client.get("/me/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["uid"] == "test_user"
        assert data["total_matches"] == 5
        assert data["total_wins"] == 3
        mock_journal_service.get_dashboard_stats.assert_called_once_with("test_user")

    def test_get_stats_user_not_found_returns_404(self, client, mock_journal_service):
        """Service ValueError maps to 404."""
        mock_journal_service.get_dashboard_stats.side_effect = ValueError(
            "User not found"
        )

        response = client.get("/me/stats")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /me/north-star
# ---------------------------------------------------------------------------


class TestSetNorthStar:
    def test_set_north_star_returns_200(self, client, mock_journal_service):
        """Returns 200 with NorthStarGoal payload."""
        now = datetime.now(timezone.utc)
        mock_journal_service.set_north_star.return_value = NorthStarGoal(
            goal_text="Win 10 matches",
            progress_pct=0.0,
            created_at=now,
        )

        payload = {"goal_text": "Win 10 matches"}
        response = client.put("/me/north-star", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["goal_text"] == "Win 10 matches"
        assert data["progress_pct"] == 0.0
        mock_journal_service.set_north_star.assert_called_once_with(
            "test_user",
            goal_text="Win 10 matches",
            target_date=None,
        )

    def test_set_north_star_user_not_found_returns_404(
        self, client, mock_journal_service
    ):
        """Service ValueError maps to 404."""
        mock_journal_service.set_north_star.side_effect = ValueError("User not found")

        response = client.put("/me/north-star", json={"goal_text": "Win 10 matches"})

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /me/journal/{entry_id}
# ---------------------------------------------------------------------------


class TestGetJournalEntry:
    def test_get_entry_returns_200(self, client, mock_journal_service):
        """Returns 200 with JournalEntry for an existing entry."""
        mock_journal_service.get_entry.return_value = _make_entry("e1")

        response = client.get("/me/journal/e1")

        assert response.status_code == 200
        data = response.json()
        assert data["entry_id"] == "e1"
        mock_journal_service.get_entry.assert_called_once_with("test_user", "e1")

    def test_get_entry_not_found_returns_404(self, client, mock_journal_service):
        """Returns 404 when service returns None (entry not found or wrong user)."""
        mock_journal_service.get_entry.return_value = None

        response = client.get("/me/journal/missing")

        assert response.status_code == 404
