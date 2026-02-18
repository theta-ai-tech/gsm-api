"""UT-02: Unit tests for JournalRepo (mock Firestore client)."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.models.enums import (
    JournalEntryTypeEnum,
    JournalVisibilityEnum,
    MatchResultEnum,
    SportEnum,
)
from app.repos.journal_repo import JournalRepo

NOW = datetime.now(timezone.utc)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    return Mock()


@pytest.fixture
def repo(mock_client):
    return JournalRepo(mock_client)


@pytest.fixture
def sample_entry_doc():
    """Minimal valid Firestore document dict for a journal entry."""
    return {
        "uid": "user123",
        "createdAt": NOW,
        "title": "Match vs Bob",
        "body": "Played well today",
        "tags": ["forehand", "serve"],
        "matchId": "match456",
        "sport": "tennis",
        "visibility": "private",
        "entryType": "match",
        "durationMinutes": None,
        "trainingFocus": [],
        "reflection": None,
        "scoreText": "6-4 7-5",
        "result": "W",
    }


def _subcollection(mock_client, uid: str = "user123"):
    """Return the mock object that represents the journalEntries subcollection."""
    return (
        mock_client.collection.return_value.document.return_value.collection.return_value  # collection("users")  # .document(uid)  # .collection("journalEntries")
    )


def _doc_ref(mock_client, uid: str = "user123"):
    """Return the mock object that represents a specific document ref."""
    return _subcollection(mock_client, uid).document.return_value


# ── create_entry ──────────────────────────────────────────────────────────────


class TestJournalRepoCreateEntry:
    def test_calls_set_and_returns_doc_id(self, repo, mock_client, sample_entry_doc):
        """create_entry calls .set() on auto-id doc_ref and returns its ID."""
        mock_doc_ref = Mock()
        mock_doc_ref.id = "new_entry_id"
        _subcollection(mock_client).document.return_value = mock_doc_ref

        entry_id = repo.create_entry("user123", sample_entry_doc)

        assert entry_id == "new_entry_id"
        # Subcollection path: collection("users").document(uid).collection("journalEntries")
        mock_client.collection.assert_called_with("users")
        mock_client.collection.return_value.document.assert_called_with("user123")
        mock_client.collection.return_value.document.return_value.collection.assert_called_with(
            "journalEntries"
        )
        # Auto-ID document: .document() called with no arguments
        _subcollection(mock_client).document.assert_called_once_with()
        mock_doc_ref.set.assert_called_once_with(sample_entry_doc)


# ── update_entry ──────────────────────────────────────────────────────────────


class TestJournalRepoUpdateEntry:
    def test_calls_update_with_correct_field_paths(self, repo, mock_client):
        """update_entry calls .update() on the correct document with the given dict."""
        updates = {"reflection": {"wentWell": ["serve"], "wentWrong": []}}

        repo.update_entry("user123", "entry_abc", updates)

        _subcollection(mock_client).document.assert_called_once_with("entry_abc")
        _doc_ref(mock_client).update.assert_called_once_with(updates)

    def test_passes_updates_dict_unchanged(self, repo, mock_client):
        """update_entry does not transform the updates dict."""
        updates = {"scoreText": "6-3 7-5", "result": "W"}

        repo.update_entry("user123", "entry_xyz", updates)

        _doc_ref(mock_client).update.assert_called_once_with(updates)


# ── get_entry ─────────────────────────────────────────────────────────────────


class TestJournalRepoGetEntry:
    def test_returns_journal_entry_for_existing_doc(
        self, repo, mock_client, sample_entry_doc
    ):
        """get_entry maps a Firestore doc to a JournalEntry model."""
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.id = "entry_abc"
        mock_doc.to_dict.return_value = sample_entry_doc
        _doc_ref(mock_client).get.return_value = mock_doc
        _subcollection(
            mock_client
        ).document.return_value = mock_doc  # ← ensures _doc_to_dict sees mock_doc

        # Wire up correctly: document("entry_abc").get() → mock_doc
        mock_doc_ref = Mock()
        mock_doc_ref.exists = True
        mock_doc_ref.id = "entry_abc"
        mock_doc_ref.to_dict.return_value = sample_entry_doc
        mock_doc_ref.get.return_value = mock_doc_ref
        _subcollection(mock_client).document.return_value = mock_doc_ref

        entry = repo.get_entry("user123", "entry_abc")

        assert entry is not None
        assert entry.entry_id == "entry_abc"
        assert entry.uid == "user123"
        assert entry.title == "Match vs Bob"
        assert entry.sport == SportEnum.TENNIS
        assert entry.visibility == JournalVisibilityEnum.PRIVATE
        assert entry.entry_type == JournalEntryTypeEnum.MATCH
        assert entry.score_text == "6-4 7-5"
        assert entry.result == MatchResultEnum.WIN

    def test_returns_none_for_missing_doc(self, repo, mock_client):
        """get_entry returns None when the document does not exist."""
        mock_doc = Mock()
        mock_doc.exists = False
        mock_doc.get.return_value = mock_doc
        _subcollection(mock_client).document.return_value = mock_doc

        entry = repo.get_entry("user123", "nonexistent")

        assert entry is None


# ── list_entries ──────────────────────────────────────────────────────────────


class TestJournalRepoListEntries:
    def _make_query_mock(self, mock_client, docs):
        """Wire up a chainable query mock that yields `docs` from .stream()."""
        mock_q = Mock()
        mock_q.order_by.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.stream.return_value = docs
        mock_client.collection.return_value.document.return_value.collection.return_value = mock_q
        return mock_q

    def test_returns_empty_list_for_user_with_no_entries(self, repo, mock_client):
        """list_entries returns [] when Firestore returns no documents."""
        self._make_query_mock(mock_client, [])

        entries = repo.list_entries("user123")

        assert entries == []

    def test_applies_no_cursor_when_cursor_is_none(self, repo, mock_client):
        """list_entries with cursor=None does not call start_after."""
        mock_q = self._make_query_mock(mock_client, [])

        repo.list_entries("user123", cursor=None)

        mock_q.start_after.assert_not_called()

    def test_applies_cursor_when_provided(self, repo, mock_client, sample_entry_doc):
        """list_entries calls start_after when a valid cursor dict is supplied."""
        mock_q = self._make_query_mock(mock_client, [])

        cursor = {"createdAt": NOW, "entryId": "entry_abc"}

        # _apply_cursor looks up the doc_ref for the cursor position;
        # wire a separate mock for that path.
        mock_cursor_doc_ref = Mock()
        # The cursor call is: client.collection("users").document(uid)
        #   .collection("journalEntries").document(entry_id)
        # Our _make_query_mock already set .collection.return_value = mock_q,
        # so we attach .document.return_value on mock_q.
        mock_q.document.return_value = mock_cursor_doc_ref
        mock_q.start_after.return_value = mock_q

        repo.list_entries("user123", cursor=cursor)

        mock_q.start_after.assert_called_once_with(NOW, mock_cursor_doc_ref)
