from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.models.common import (
    JournalEntrySummary,
    PerSportLevels,
    PerSportRankings,
    UserPreferences,
)
from app.models.enums import (
    JournalEntryTypeEnum,
    JournalVisibilityEnum,
    SportEnum,
    TrainingFocusEnum,
)
from app.models.journal import (
    CreateJournalEntryRequest,
    JournalEntry,
    MatchReflection,
    UpdateJournalEntryRequest,
)
from app.models.user import PrivateUserProfile
from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.users_repo import UsersRepo
from app.services.journal_service import JournalService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    uid: str = "test_user",
    journal_recent: list | None = None,
    completed_matches: list | None = None,
) -> PrivateUserProfile:
    return PrivateUserProfile(
        uid=uid,
        name="Test User",
        email="test@example.com",
        rankings=PerSportRankings(),
        preferences=UserPreferences(
            area=10001,
            levels=PerSportLevels(),
            sports=[],
        ),
        journal_recent=journal_recent or [],
        completed_matches=completed_matches or [],
    )


def _make_entry(
    entry_id: str = "e1",
    uid: str = "test_user",
) -> JournalEntry:
    return JournalEntry(
        entry_id=entry_id,
        uid=uid,
        created_at=datetime.now(timezone.utc),
        title="Test Entry",
        body="Body text",
        visibility=JournalVisibilityEnum.PRIVATE,
        entry_type=JournalEntryTypeEnum.MATCH,
    )


def _setup_create_mocks(
    mock_firestore_client: Mock,
    entry_id: str = "entry123",
    existing_recent: list | None = None,
) -> tuple[Mock, Mock, Mock]:
    """
    Wire up the Firestore call chain used by JournalService.create_entry.

    Returns (mock_txn, mock_user_doc, mock_entry_ref).
    """
    mock_entry_ref = Mock()
    mock_entry_ref.id = entry_id

    mock_snap = Mock()
    mock_snap.to_dict.return_value = {"journalRecent": existing_recent or []}

    mock_user_doc = Mock()
    mock_user_doc.get.return_value = mock_snap
    mock_user_doc.collection.return_value.document.return_value = mock_entry_ref

    mock_firestore_client.collection.return_value.document.return_value = mock_user_doc

    mock_txn = Mock()
    mock_firestore_client.transaction.return_value = mock_txn

    return mock_txn, mock_user_doc, mock_entry_ref


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_users_repo():
    return Mock(spec=UsersRepo)


@pytest.fixture
def mock_journal_repo():
    return Mock(spec=JournalRepo)


@pytest.fixture
def mock_matches_repo():
    return Mock(spec=MatchesRepo)


@pytest.fixture
def mock_firestore_client():
    return Mock()


@pytest.fixture
def journal_service(
    mock_users_repo, mock_journal_repo, mock_matches_repo, mock_firestore_client
):
    return JournalService(
        mock_users_repo, mock_journal_repo, mock_matches_repo, mock_firestore_client
    )


# ---------------------------------------------------------------------------
# TestCreateEntry
# ---------------------------------------------------------------------------


class TestCreateEntry:
    def test_create_match_entry(
        self,
        journal_service,
        mock_users_repo,
        mock_matches_repo,
        mock_firestore_client,
    ):
        """Match entry is created atomically — response carries entry_id."""
        mock_users_repo.get_user_doc.return_value = {
            "uid": "test_user",
            "name": "Test User",
        }
        mock_matches_repo.get_by_id.return_value = None  # lenient — just logs warning
        _setup_create_mocks(mock_firestore_client, entry_id="entry123")

        import app.services.journal_service as svc_module

        original = svc_module.firestore.transactional
        svc_module.firestore.transactional = lambda func: func
        try:
            request = CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.MATCH,
                title="Great match",
                body="Played well",
                sport=SportEnum.TENNIS,
            )
            response = journal_service.create_entry("test_user", request)

            assert response.entry_id == "entry123"
            assert isinstance(response.created_at, datetime)
        finally:
            svc_module.firestore.transactional = original

    def test_create_training_entry(
        self,
        journal_service,
        mock_users_repo,
        mock_firestore_client,
    ):
        """Training entry stores duration and focus in the Firestore doc."""
        mock_users_repo.get_user_doc.return_value = {"uid": "test_user"}
        mock_txn, _, _ = _setup_create_mocks(mock_firestore_client, entry_id="train123")

        import app.services.journal_service as svc_module

        original = svc_module.firestore.transactional
        svc_module.firestore.transactional = lambda func: func
        try:
            request = CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.TRAINING,
                title="Serve session",
                body="Worked on serve",
                duration_minutes=60,
                training_focus=[TrainingFocusEnum.SERVE],
                sport=SportEnum.TENNIS,
            )
            response = journal_service.create_entry("test_user", request)

            assert response.entry_id == "train123"
            # Inspect the entry doc written via txn.set
            entry_data = mock_txn.set.call_args[0][1]
            assert entry_data["entryType"] == "training"
            assert entry_data["durationMinutes"] == 60
            assert "serve" in entry_data["trainingFocus"]
        finally:
            svc_module.firestore.transactional = original

    def test_create_entry_user_not_found(
        self,
        journal_service,
        mock_users_repo,
    ):
        """Raises ValueError when the user doc does not exist."""
        mock_users_repo.get_user_doc.return_value = None

        request = CreateJournalEntryRequest(
            entry_type=JournalEntryTypeEnum.MATCH,
            title="Test",
        )

        with pytest.raises(ValueError, match="User not found"):
            journal_service.create_entry("ghost_user", request)

    def test_create_entry_cache_caps_at_10(
        self,
        journal_service,
        mock_users_repo,
        mock_firestore_client,
    ):
        """journalRecent is capped at 10 after prepending the new summary."""
        mock_users_repo.get_user_doc.return_value = {"uid": "test_user"}
        now = datetime.now(timezone.utc)
        existing = [
            {
                "entryId": f"old_{i}",
                "createdAt": now - timedelta(days=i + 1),
                "title": f"Entry {i}",
            }
            for i in range(10)
        ]
        mock_txn, _, _ = _setup_create_mocks(
            mock_firestore_client, entry_id="new_entry", existing_recent=existing
        )

        import app.services.journal_service as svc_module

        original = svc_module.firestore.transactional
        svc_module.firestore.transactional = lambda func: func
        try:
            request = CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.MATCH,
                title="New entry",
            )
            journal_service.create_entry("test_user", request)

            updated_recent = mock_txn.update.call_args[0][1]["journalRecent"]
            assert len(updated_recent) == 10
            assert updated_recent[0]["entryId"] == "new_entry"
        finally:
            svc_module.firestore.transactional = original


# ---------------------------------------------------------------------------
# TestUpdateEntry
# ---------------------------------------------------------------------------


class TestUpdateEntry:
    def test_update_entry_reflection_merged(
        self,
        journal_service,
        mock_journal_repo,
    ):
        """Reflection tags are serialised and forwarded to journal_repo.update_entry."""
        mock_journal_repo.get_entry.return_value = _make_entry()

        request = UpdateJournalEntryRequest(
            reflection=MatchReflection(
                went_well=["first_serve", "net_play"],
                went_wrong=["double_faults"],
            )
        )
        journal_service.update_entry("test_user", "e1", request)

        mock_journal_repo.update_entry.assert_called_once()
        updates = mock_journal_repo.update_entry.call_args[0][2]
        assert "reflection" in updates
        assert updates["reflection"]["wentWell"] == ["first_serve", "net_play"]
        assert updates["reflection"]["wentWrong"] == ["double_faults"]

    def test_update_entry_not_found(
        self,
        journal_service,
        mock_journal_repo,
    ):
        """Raises ValueError when the entry does not exist."""
        mock_journal_repo.get_entry.return_value = None

        with pytest.raises(ValueError, match="not found"):
            journal_service.update_entry(
                "test_user", "missing", UpdateJournalEntryRequest(tags=["x"])
            )

    def test_update_entry_wrong_user(
        self,
        journal_service,
        mock_journal_repo,
    ):
        """Raises ValueError when the entry belongs to a different user."""
        mock_journal_repo.get_entry.return_value = _make_entry(uid="other_user")

        with pytest.raises(ValueError, match="does not belong"):
            journal_service.update_entry(
                "test_user", "e1", UpdateJournalEntryRequest(tags=["x"])
            )


# ---------------------------------------------------------------------------
# TestListEntries
# ---------------------------------------------------------------------------


class TestListEntries:
    def test_list_entries_delegates_to_repo(
        self,
        journal_service,
        mock_journal_repo,
    ):
        """list_entries passes uid, limit, and cursor through to JournalRepo."""
        expected = [_make_entry("e1"), _make_entry("e2")]
        mock_journal_repo.list_entries.return_value = expected

        result = journal_service.list_entries("test_user", limit=5)

        mock_journal_repo.list_entries.assert_called_once_with(
            "test_user", limit=5, cursor=None
        )
        assert result == expected


# ---------------------------------------------------------------------------
# TestGetDashboardStats
# ---------------------------------------------------------------------------


class TestGetDashboardStats:
    def test_get_stats_empty_user_returns_zero_stats(
        self,
        journal_service,
        mock_users_repo,
    ):
        """All counters are 0 for a user with no activity."""
        mock_users_repo.get_private_profile.return_value = _make_profile()

        stats = journal_service.get_dashboard_stats("test_user")

        assert stats.uid == "test_user"
        assert stats.total_matches == 0
        assert stats.total_wins == 0
        assert stats.total_training_sessions == 0
        assert stats.current_streak == 0

    def test_get_stats_streak_from_recent_entries(
        self,
        journal_service,
        mock_users_repo,
    ):
        """Streak is 1 when the user has an entry dated today."""
        today = datetime.now(timezone.utc)
        recent = [
            JournalEntrySummary(
                entry_id="e1",
                created_at=today,
                title="Today's match",
                entry_type=JournalEntryTypeEnum.MATCH,
            )
        ]
        mock_users_repo.get_private_profile.return_value = _make_profile(
            journal_recent=recent
        )

        stats = journal_service.get_dashboard_stats("test_user")

        assert stats.current_streak == 1

    def test_get_stats_user_not_found(
        self,
        journal_service,
        mock_users_repo,
    ):
        """Raises ValueError when the private profile cannot be loaded."""
        mock_users_repo.get_private_profile.return_value = None

        with pytest.raises(ValueError, match="User not found"):
            journal_service.get_dashboard_stats("ghost")


# ---------------------------------------------------------------------------
# TestSetNorthStar
# ---------------------------------------------------------------------------


class TestSetNorthStar:
    def test_set_north_star_persists_goal(
        self,
        journal_service,
        mock_firestore_client,
    ):
        """NorthStarGoal is written to Firestore and returned with correct fields."""
        goal_text = "Win 10 matches this month"

        result = journal_service.set_north_star("test_user", goal_text)

        assert result.goal_text == goal_text
        assert result.progress_pct == 0.0
        assert isinstance(result.created_at, datetime)
        assert result.target_date is None

        # Verify the Firestore update was issued
        update_mock = (
            mock_firestore_client.collection.return_value.document.return_value.update
        )
        update_mock.assert_called_once()
        goal_data = update_mock.call_args[0][0]["northStarGoal"]
        assert goal_data["goalText"] == goal_text
        assert goal_data["progressPct"] == 0.0
