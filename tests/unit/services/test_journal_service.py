from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.models.common import (
    JournalEntrySummary,
    PerSportLevels,
    PerSportRankings,
    UserCompletedMatchSummary,
    UserPreferences,
)
from app.models.enums import (
    JournalEntryTypeEnum,
    JournalVisibilityEnum,
    MatchResultEnum,
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
from app.services.journal_service import (
    JournalEntryNotFoundError,
    JournalInvalidCursorError,
    JournalRateLimitError,
    JournalService,
    UnsupportedJournalFilterError,
)


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
    repo = Mock(spec=JournalRepo)
    repo.count_entries_since.return_value = 0
    repo.get_entry_by_client_request_id.return_value = None
    return repo


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
            assert updated_recent[1]["entryId"] == "old_0"
        finally:
            svc_module.firestore.transactional = original

    def test_create_entry_denormalises_result_from_match(
        self,
        journal_service,
        mock_users_repo,
        mock_matches_repo,
        mock_firestore_client,
    ):
        """When request.result is unset, resultByUser from match is denormalised."""
        mock_users_repo.get_user_doc.return_value = {"uid": "test_user"}
        mock_txn, _, _ = _setup_create_mocks(mock_firestore_client, entry_id="entry123")
        mock_matches_repo.get_by_id.return_value = Mock(
            participant_uids=["test_user", "other"],
            result_by_user={"test_user": MatchResultEnum.WIN},
        )

        import app.services.journal_service as svc_module

        original = svc_module.firestore.transactional
        svc_module.firestore.transactional = lambda func: func
        try:
            request = CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.MATCH,
                title="Great match",
                match_id="m1",
            )
            journal_service.create_entry("test_user", request)

            entry_data = mock_txn.set.call_args[0][1]
            assert entry_data["result"] == MatchResultEnum.WIN.value
            mock_matches_repo.get_by_id.assert_called_once_with("m1")
        finally:
            svc_module.firestore.transactional = original

    def test_create_entry_preserves_explicit_result(
        self,
        journal_service,
        mock_users_repo,
        mock_matches_repo,
        mock_firestore_client,
    ):
        """request.result takes precedence over denormalised match result."""
        mock_users_repo.get_user_doc.return_value = {"uid": "test_user"}
        mock_txn, _, _ = _setup_create_mocks(mock_firestore_client, entry_id="entry123")
        mock_matches_repo.get_by_id.return_value = Mock(
            participant_uids=["test_user", "other"],
            result_by_user={"test_user": MatchResultEnum.LOSS},
        )

        import app.services.journal_service as svc_module

        original = svc_module.firestore.transactional
        svc_module.firestore.transactional = lambda func: func
        try:
            request = CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.MATCH,
                title="Great match",
                match_id="m1",
                result=MatchResultEnum.WIN,
            )
            journal_service.create_entry("test_user", request)

            entry_data = mock_txn.set.call_args[0][1]
            assert entry_data["result"] == MatchResultEnum.WIN.value
        finally:
            svc_module.firestore.transactional = original

    def test_create_training_entry_does_not_lookup_match(
        self,
        journal_service,
        mock_users_repo,
        mock_matches_repo,
        mock_firestore_client,
    ):
        """Training entry should not hit matches_repo.get_by_id."""
        mock_users_repo.get_user_doc.return_value = {"uid": "test_user"}
        _setup_create_mocks(mock_firestore_client, entry_id="entry123")

        import app.services.journal_service as svc_module

        original = svc_module.firestore.transactional
        svc_module.firestore.transactional = lambda func: func
        try:
            request = CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.TRAINING,
                title="Serve session",
                duration_minutes=30,
                training_focus=[TrainingFocusEnum.SERVE],
            )
            journal_service.create_entry("test_user", request)

            mock_matches_repo.get_by_id.assert_not_called()
        finally:
            svc_module.firestore.transactional = original

    def test_create_entry_rate_limited_raises_error(
        self,
        journal_service,
        mock_users_repo,
        mock_journal_repo,
    ):
        """Create is rejected when the per-hour threshold is exceeded."""
        mock_users_repo.get_user_doc.return_value = {"uid": "test_user"}
        mock_journal_repo.count_entries_since.return_value = 50

        request = CreateJournalEntryRequest(
            entry_type=JournalEntryTypeEnum.MATCH,
            title="Rate-limited",
        )

        with pytest.raises(JournalRateLimitError, match="Rate limit exceeded"):
            journal_service.create_entry("test_user", request)

    def test_create_entry_with_client_request_id_returns_existing_entry(
        self,
        journal_service,
        mock_users_repo,
        mock_journal_repo,
        mock_firestore_client,
    ):
        """Idempotency: existing clientRequestId returns existing entry and avoids writes."""
        mock_users_repo.get_user_doc.return_value = {"uid": "test_user"}
        existing = _make_entry(entry_id="existing_1")
        mock_journal_repo.get_entry_by_client_request_id.return_value = existing

        request = CreateJournalEntryRequest(
            entry_type=JournalEntryTypeEnum.MATCH,
            title="Retry create",
            client_request_id="client-req-123",
        )
        response = journal_service.create_entry("test_user", request)

        assert response.entry_id == "existing_1"
        assert response.created_at == existing.created_at
        mock_firestore_client.transaction.assert_not_called()

    def test_create_entry_with_client_request_id_scopes_to_user(
        self,
        journal_service,
        mock_users_repo,
        mock_journal_repo,
        mock_firestore_client,
    ):
        """Idempotency lookup is user-scoped through JournalRepo(uid, clientRequestId)."""
        mock_users_repo.get_user_doc.return_value = {"uid": "test_user"}
        _setup_create_mocks(mock_firestore_client, entry_id="entry123")

        import app.services.journal_service as svc_module

        original = svc_module.firestore.transactional
        svc_module.firestore.transactional = lambda func: func
        try:
            request = CreateJournalEntryRequest(
                entry_type=JournalEntryTypeEnum.MATCH,
                title="Create once",
                client_request_id="client-req-123",
            )
            journal_service.create_entry("test_user", request)

            mock_journal_repo.get_entry_by_client_request_id.assert_called_once_with(
                "test_user", "client-req-123"
            )
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

        with pytest.raises(JournalEntryNotFoundError, match="not found"):
            journal_service.update_entry(
                "test_user", "missing", UpdateJournalEntryRequest(tags=["x"])
            )

    def test_update_entry_cross_user_returns_not_found(
        self,
        journal_service,
        mock_journal_repo,
    ):
        """Entry not found under the caller's subcollection raises not-found."""
        mock_journal_repo.get_entry.return_value = None

        with pytest.raises(JournalEntryNotFoundError, match="not found"):
            journal_service.update_entry(
                "test_user", "foreign_entry", UpdateJournalEntryRequest(tags=["x"])
            )

    def test_update_entry_no_fields_is_noop(
        self,
        journal_service,
        mock_journal_repo,
    ):
        """No provided update fields should skip repository write."""
        mock_journal_repo.get_entry.return_value = _make_entry()

        journal_service.update_entry("test_user", "e1", UpdateJournalEntryRequest())

        mock_journal_repo.update_entry.assert_not_called()

    def test_update_entry_tags_and_body(
        self,
        journal_service,
        mock_journal_repo,
    ):
        """tags/body are forwarded in camelCase update payload."""
        mock_journal_repo.get_entry.return_value = _make_entry()

        journal_service.update_entry(
            "test_user",
            "e1",
            UpdateJournalEntryRequest(tags=["focus"], body="Updated body"),
        )

        updates = mock_journal_repo.update_entry.call_args[0][2]
        assert updates["tags"] == ["focus"]
        assert updates["body"] == "Updated body"


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

    def test_list_entries_with_cursor_delegates_to_repo(
        self,
        journal_service,
        mock_journal_repo,
    ):
        """Cursor is passed through unchanged to JournalRepo."""
        cursor = {"createdAt": datetime.now(timezone.utc), "entryId": "e1"}
        mock_journal_repo.get_entry.return_value = _make_entry("e1")
        mock_journal_repo.list_entries.return_value = []

        journal_service.list_entries("test_user", limit=3, cursor=cursor)

        mock_journal_repo.list_entries.assert_called_once_with(
            "test_user", limit=3, cursor=cursor
        )

    def test_list_entries_rejects_invalid_cursor(
        self, journal_service, mock_journal_repo
    ):
        """Cursor entry IDs that do not exist for caller are rejected."""
        cursor = {"createdAt": datetime.now(timezone.utc), "entryId": "missing"}
        mock_journal_repo.get_entry.return_value = None

        with pytest.raises(JournalInvalidCursorError, match="Invalid cursor"):
            journal_service.list_entries("test_user", limit=3, cursor=cursor)

    def test_list_entries_rejects_foreign_cursor(
        self, journal_service, mock_journal_repo
    ):
        """Foreign cursor entry IDs are rejected as invalid cursor (not found under user)."""
        cursor = {"createdAt": datetime.now(timezone.utc), "entryId": "foreign"}
        mock_journal_repo.get_entry.return_value = None

        with pytest.raises(JournalInvalidCursorError, match="Invalid cursor"):
            journal_service.list_entries("test_user", limit=3, cursor=cursor)

    def test_list_entries_rejects_filters_for_now(self, journal_service):
        """Filter params are part of contract but not implemented yet."""
        with pytest.raises(
            UnsupportedJournalFilterError, match="filter not supported yet"
        ):
            journal_service.list_entries("test_user", entry_type="match")


# ---------------------------------------------------------------------------
# TestGetEntry
# ---------------------------------------------------------------------------


class TestGetEntry:
    def test_get_entry_delegates_to_repo(
        self,
        journal_service,
        mock_journal_repo,
    ):
        """Service get_entry is a thin pass-through."""
        entry = _make_entry("e42")
        mock_journal_repo.get_entry.return_value = entry

        result = journal_service.get_entry("test_user", "e42")

        assert result == entry
        mock_journal_repo.get_entry.assert_called_once_with("test_user", "e42")

    def test_get_entry_cross_user_returns_none(
        self, journal_service, mock_journal_repo
    ):
        """Entry not found under the caller's subcollection returns None (→ 404)."""
        mock_journal_repo.get_entry.return_value = None

        result = journal_service.get_entry("test_user", "foreign_entry")

        assert result is None


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


# ---------------------------------------------------------------------------
# TestGetNorthStar
# ---------------------------------------------------------------------------


class TestGetNorthStar:
    def test_get_north_star_returns_none_when_user_missing(
        self,
        journal_service,
        mock_users_repo,
    ):
        """Missing user doc returns None."""
        mock_users_repo.get_user_doc.return_value = None

        result = journal_service.get_north_star("ghost")

        assert result is None

    def test_get_north_star_parses_existing_goal(
        self,
        journal_service,
        mock_users_repo,
    ):
        """Existing northStarGoal payload is parsed into NorthStarGoal."""
        created_at = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "northStarGoal": {
                "goalText": "Win tournament",
                "progressPct": 20.0,
                "createdAt": created_at,
                "targetDate": None,
            }
        }

        result = journal_service.get_north_star("test_user")

        assert result is not None
        assert result.goal_text == "Win tournament"
        assert result.progress_pct == 20.0
        assert result.created_at == created_at


# ---------------------------------------------------------------------------
# TestDeleteEntry
# ---------------------------------------------------------------------------


class TestDeleteEntry:
    def test_delete_entry_soft_deletes_and_updates_cache(
        self,
        journal_service,
        mock_journal_repo,
        mock_firestore_client,
    ):
        """delete_entry marks doc as deleted and removes summary from journalRecent."""
        mock_journal_repo.get_entry.return_value = _make_entry("e1", uid="test_user")

        mock_txn = Mock()
        mock_firestore_client.transaction.return_value = mock_txn

        mock_snap = Mock()
        mock_snap.to_dict.return_value = {
            "journalRecent": [{"entryId": "e1"}, {"entryId": "e2"}]
        }
        mock_user_doc = Mock()
        mock_user_doc.get.return_value = mock_snap
        mock_entry_doc = Mock()
        mock_user_doc.collection.return_value.document.return_value = mock_entry_doc
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_user_doc
        )

        import app.services.journal_service as svc_module

        original = svc_module.firestore.transactional
        svc_module.firestore.transactional = lambda func: func
        try:
            journal_service.delete_entry("test_user", "e1")
        finally:
            svc_module.firestore.transactional = original

        assert mock_txn.update.call_count == 2
        first_update = mock_txn.update.call_args_list[0][0][1]
        second_update = mock_txn.update.call_args_list[1][0][1]
        assert first_update["isDeleted"] is True
        assert "deletedAt" in first_update
        assert second_update["journalRecent"] == [{"entryId": "e2"}]

    def test_delete_entry_not_found_raises(self, journal_service, mock_journal_repo):
        """Unknown entry ID is treated as not found."""
        mock_journal_repo.get_entry.return_value = None

        with pytest.raises(JournalEntryNotFoundError, match="not found"):
            journal_service.delete_entry("test_user", "missing")


# ---------------------------------------------------------------------------
# TestGetLoggableMatches
# ---------------------------------------------------------------------------


def _completed(
    match_id: str,
    finished_at: datetime,
    opponent_uid: str | None = None,
    opponent_name: str | None = None,
) -> UserCompletedMatchSummary:
    return UserCompletedMatchSummary(
        match_id=match_id,
        sport=SportEnum.TENNIS,
        finished_at=finished_at,
        result=MatchResultEnum.WIN,
        score_text="6-4 7-5",
        league_id="league_1",
        opponent_uid=opponent_uid,
        opponent_name=opponent_name,
    )


class TestGetLoggableMatches:
    def test_empty_completed_matches_returns_empty_list(
        self,
        journal_service,
        mock_users_repo,
    ):
        mock_users_repo.get_private_profile.return_value = _make_profile()

        assert journal_service.get_loggable_matches("test_user") == []

    def test_user_not_found_raises(self, journal_service, mock_users_repo):
        mock_users_repo.get_private_profile.return_value = None

        with pytest.raises(ValueError, match="User not found"):
            journal_service.get_loggable_matches("ghost")

    def test_orders_by_finished_at_desc(self, journal_service, mock_users_repo):
        older = _completed("m_old", datetime(2030, 1, 1, tzinfo=timezone.utc))
        newer = _completed("m_new", datetime(2030, 1, 5, tzinfo=timezone.utc))
        mock_users_repo.get_private_profile.return_value = _make_profile(
            completed_matches=[older, newer]
        )

        result = journal_service.get_loggable_matches("test_user")

        assert [m.match_id for m in result] == ["m_new", "m_old"]

    def test_already_logged_flag_and_field_values(
        self,
        journal_service,
        mock_users_repo,
    ):
        logged = _completed(
            "m_logged",
            datetime(2030, 1, 5, tzinfo=timezone.utc),
            opponent_uid="user_rival",
            opponent_name="Rival Rick",
        )
        unlogged = _completed(
            "m_unlogged",
            datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        recent = [
            JournalEntrySummary(
                entry_id="e1",
                created_at=datetime(2030, 1, 6, tzinfo=timezone.utc),
                title="Match win",
                match_id="m_logged",
                entry_type=JournalEntryTypeEnum.MATCH,
            )
        ]
        mock_users_repo.get_private_profile.return_value = _make_profile(
            journal_recent=recent,
            completed_matches=[logged, unlogged],
        )

        result = journal_service.get_loggable_matches("test_user")

        by_id = {m.match_id: m for m in result}
        assert by_id["m_logged"].already_logged is True
        assert by_id["m_logged"].opponent_uid == "user_rival"
        assert by_id["m_logged"].opponent_name == "Rival Rick"
        assert by_id["m_logged"].score_text == "6-4 7-5"
        assert by_id["m_logged"].result == MatchResultEnum.WIN
        assert by_id["m_unlogged"].already_logged is False

    def test_delete_entry_cross_user_returns_not_found(
        self, journal_service, mock_journal_repo
    ):
        """Entry not found under the caller's subcollection raises not-found."""
        mock_journal_repo.get_entry.return_value = None

        with pytest.raises(JournalEntryNotFoundError, match="not found"):
            journal_service.delete_entry("test_user", "foreign")
