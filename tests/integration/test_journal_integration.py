"""
Integration tests for Tab 2 IMPROVE — Journal CRUD.

Tests verify end-to-end behavior of JournalService against the real Firestore
emulator, including atomic transactions, cache updates, reflection merges,
cursor-based pagination, and the journalRecent cap invariant.

Requires: FIRESTORE_EMULATOR_HOST env var set (e.g. via `make emu-all`)
"""

from datetime import datetime, timezone

import pytest

from app.models.enums import JournalEntryTypeEnum, SportEnum, TrainingFocusEnum
from app.models.journal import (
    CreateJournalEntryRequest,
    MatchReflection,
    UpdateJournalEntryRequest,
)
from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.users_repo import UsersRepo
from app.services.journal_service import JournalInvalidCursorError, JournalService

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_journal_service(db) -> JournalService:
    """Create a JournalService backed by real repos against the emulator."""
    return JournalService(
        UsersRepo(db),
        JournalRepo(db),
        MatchesRepo(db),
        db,
    )


def seed_user(db, uid: str, name: str = "Test User") -> None:
    """Seed a minimal user doc (no journal activity)."""
    db.collection("users").document(uid).set(
        {
            "name": name,
            "email": f"{uid}@test.com",
            "rankings": {},
            "journalRecent": [],
            "playTab": {
                "state": "DISCOVERY",
                "updatedAt": datetime.now(timezone.utc),
            },
        }
    )


def get_user_doc(db, uid: str) -> dict:
    """Fetch the full user document as a dict."""
    doc = db.collection("users").document(uid).get()
    return doc.to_dict() if doc.exists else {}


def get_entry_doc(db, uid: str, entry_id: str) -> dict:
    """Fetch a single journal entry doc as a dict (empty if not found)."""
    doc = (
        db.collection("users")
        .document(uid)
        .collection("journalEntries")
        .document(entry_id)
        .get()
    )
    return doc.to_dict() if doc.exists else {}


def make_match_request(**kwargs) -> CreateJournalEntryRequest:
    """Return a minimal match CreateJournalEntryRequest."""
    defaults = dict(
        entry_type=JournalEntryTypeEnum.MATCH,
        title="Test match",
        body="",
        sport=SportEnum.TENNIS,
    )
    defaults.update(kwargs)
    return CreateJournalEntryRequest(**defaults)


def make_training_request(**kwargs) -> CreateJournalEntryRequest:
    """Return a minimal training CreateJournalEntryRequest."""
    defaults = dict(
        entry_type=JournalEntryTypeEnum.TRAINING,
        title="Training session",
        body="",
        sport=SportEnum.TENNIS,
        duration_minutes=60,
        training_focus=[TrainingFocusEnum.SERVE],
    )
    defaults.update(kwargs)
    return CreateJournalEntryRequest(**defaults)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_journal_entries(db):
    """Delete journal entry subcollections after each test.

    The root conftest deletes user docs; subcollections survive unless explicitly
    removed. Use unique UIDs per test to avoid cross-test contamination.
    """
    yield
    for user_doc in db.collection("users").stream():
        for entry_doc in user_doc.reference.collection("journalEntries").stream():
            entry_doc.reference.delete()


# ---------------------------------------------------------------------------
# IT-01-1: Create match entry → verify Firestore doc and cache
# ---------------------------------------------------------------------------


class TestCreateMatchEntry:
    def test_entry_doc_written_with_correct_fields(self, db):
        """Entry document created with all expected camelCase fields."""
        uid = "alice_create_match_doc"
        seed_user(db, uid)
        service = make_journal_service(db)

        response = service.create_entry(uid, make_match_request(title="Great match"))

        doc = get_entry_doc(db, uid, response.entry_id)
        assert doc, "Journal entry doc should exist"
        assert doc["title"] == "Great match"
        assert doc["entryType"] == "match"
        assert doc["sport"] == "tennis"
        assert doc["reflection"] is None
        assert "createdAt" in doc

    def test_journal_recent_cache_updated_on_create(self, db):
        """journalRecent on user doc is updated atomically when entry is created."""
        uid = "alice_create_match_cache"
        seed_user(db, uid)
        service = make_journal_service(db)

        response = service.create_entry(uid, make_match_request(title="My match"))

        user = get_user_doc(db, uid)
        recent = user.get("journalRecent", [])
        assert len(recent) == 1
        assert recent[0]["entryId"] == response.entry_id
        assert recent[0]["title"] == "My match"
        assert recent[0]["entryType"] == "match"

    def test_multiple_entries_appear_newest_first_in_cache(self, db):
        """journalRecent is ordered newest-first (prepend semantics)."""
        uid = "alice_create_match_order"
        seed_user(db, uid)
        service = make_journal_service(db)

        resp1 = service.create_entry(uid, make_match_request(title="First"))
        resp2 = service.create_entry(uid, make_match_request(title="Second"))

        user = get_user_doc(db, uid)
        recent = user.get("journalRecent", [])
        # Second (newer) should be first in the list
        assert recent[0]["entryId"] == resp2.entry_id
        assert recent[1]["entryId"] == resp1.entry_id


# ---------------------------------------------------------------------------
# IT-01-2: Create training entry → verify trainingFocus and durationMinutes
# ---------------------------------------------------------------------------


class TestCreateTrainingEntry:
    def test_training_fields_persisted(self, db):
        """trainingFocus and durationMinutes are written to the entry doc."""
        uid = "alice_create_training_fields"
        seed_user(db, uid)
        service = make_journal_service(db)

        response = service.create_entry(
            uid,
            make_training_request(
                title="Serve drill",
                duration_minutes=45,
                training_focus=[TrainingFocusEnum.SERVE],
            ),
        )

        doc = get_entry_doc(db, uid, response.entry_id)
        assert doc["entryType"] == "training"
        assert doc["durationMinutes"] == 45
        assert "serve" in doc["trainingFocus"]

    def test_training_entry_appears_in_journal_recent(self, db):
        """Training entries appear in journalRecent with correct entryType."""
        uid = "alice_training_cache"
        seed_user(db, uid)
        service = make_journal_service(db)

        response = service.create_entry(uid, make_training_request(title="Footwork"))

        user = get_user_doc(db, uid)
        recent = user.get("journalRecent", [])
        assert len(recent) == 1
        assert recent[0]["entryId"] == response.entry_id
        assert recent[0]["entryType"] == "training"


# ---------------------------------------------------------------------------
# IT-01-3: Update with reflection → verify merge
# ---------------------------------------------------------------------------


class TestUpdateEntryReflection:
    def test_reflection_fields_persisted(self, db):
        """Reflection tags are merged into the entry doc via PATCH."""
        uid = "alice_update_reflection"
        seed_user(db, uid)
        service = make_journal_service(db)

        create_resp = service.create_entry(uid, make_match_request(title="Post-match"))

        service.update_entry(
            uid,
            create_resp.entry_id,
            UpdateJournalEntryRequest(
                reflection=MatchReflection(
                    went_well=["first_serve", "net_play"],
                    went_wrong=["double_faults"],
                    opponent_weak=["backhand"],
                    opponent_strong=["forehand"],
                )
            ),
        )

        doc = get_entry_doc(db, uid, create_resp.entry_id)
        ref = doc["reflection"]
        assert ref["wentWell"] == ["first_serve", "net_play"]
        assert ref["wentWrong"] == ["double_faults"]
        assert ref["opponentWeak"] == ["backhand"]
        assert ref["opponentStrong"] == ["forehand"]

    def test_tags_and_body_updated(self, db):
        """tags and body can be updated independently via PATCH."""
        uid = "alice_update_tags_body"
        seed_user(db, uid)
        service = make_journal_service(db)

        create_resp = service.create_entry(
            uid, make_match_request(title="Entry to update", body="Original body")
        )

        service.update_entry(
            uid,
            create_resp.entry_id,
            UpdateJournalEntryRequest(
                tags=["important", "tournament"],
                body="Updated body text",
            ),
        )

        doc = get_entry_doc(db, uid, create_resp.entry_id)
        assert doc["tags"] == ["important", "tournament"]
        assert doc["body"] == "Updated body text"

    def test_update_not_found_raises_value_error(self, db):
        """Updating a non-existent entry raises ValueError."""
        uid = "alice_update_missing"
        seed_user(db, uid)
        service = make_journal_service(db)

        with pytest.raises(ValueError, match="not found"):
            service.update_entry(
                uid, "nonexistent_id", UpdateJournalEntryRequest(tags=["x"])
            )


# ---------------------------------------------------------------------------
# IT-01-4: List entries → verify pagination
# ---------------------------------------------------------------------------


class TestListEntriesPagination:
    def test_list_entries_returns_all_without_cursor(self, db):
        """Listing without a cursor returns the most recent entries up to limit."""
        uid = "alice_list_no_cursor"
        seed_user(db, uid)
        service = make_journal_service(db)

        for i in range(5):
            service.create_entry(uid, make_match_request(title=f"Match {i}"))

        entries = service.list_entries(uid, limit=10)
        assert len(entries) == 5

    def test_list_entries_respects_limit(self, db):
        """limit parameter restricts the number of entries returned."""
        uid = "alice_list_limit"
        seed_user(db, uid)
        service = make_journal_service(db)

        for i in range(5):
            service.create_entry(uid, make_match_request(title=f"Match {i}"))

        page = service.list_entries(uid, limit=2)
        assert len(page) == 2

    def test_cursor_advances_to_next_page(self, db):
        """Cursor returned from page 1 fetches a non-overlapping page 2."""
        uid = "alice_list_cursor"
        seed_user(db, uid)
        service = make_journal_service(db)

        for i in range(5):
            service.create_entry(uid, make_match_request(title=f"Match {i}"))

        page1 = service.list_entries(uid, limit=2)
        assert len(page1) == 2

        cursor = {"createdAt": page1[-1].created_at, "entryId": page1[-1].entry_id}
        page2 = service.list_entries(uid, limit=2, cursor=cursor)
        assert len(page2) >= 1

        # No overlap between pages
        page1_ids = {e.entry_id for e in page1}
        page2_ids = {e.entry_id for e in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_empty_for_new_user(self, db):
        """User with no entries gets an empty list."""
        uid = "alice_list_empty"
        seed_user(db, uid)
        service = make_journal_service(db)

        entries = service.list_entries(uid, limit=10)
        assert entries == []


# ---------------------------------------------------------------------------
# IT-01-5: Cache consistency — journalRecent capped at 10
# ---------------------------------------------------------------------------


class TestJournalRecentCacheCap:
    def test_journal_recent_capped_at_10_after_12_creates(self, db):
        """Creating 12 entries results in exactly 10 summaries in journalRecent."""
        uid = "alice_cap_12"
        seed_user(db, uid)
        service = make_journal_service(db)

        for i in range(12):
            service.create_entry(uid, make_match_request(title=f"Match {i}"))

        user = get_user_doc(db, uid)
        recent = user.get("journalRecent", [])
        assert len(recent) == 10

    def test_journal_recent_contains_most_recent_entries(self, db):
        """After 12 creates, journalRecent holds the most-recent 10 entry IDs."""
        uid = "alice_cap_most_recent"
        seed_user(db, uid)
        service = make_journal_service(db)

        all_ids = []
        for i in range(12):
            resp = service.create_entry(uid, make_match_request(title=f"Match {i}"))
            all_ids.append(resp.entry_id)

        # The last 10 created are the most recent
        expected_ids = set(all_ids[-10:])

        user = get_user_doc(db, uid)
        cached_ids = {s["entryId"] for s in user.get("journalRecent", [])}
        assert cached_ids == expected_ids

    def test_journal_recent_exactly_10_is_not_truncated(self, db):
        """Exactly 10 entries: cache stays at 10, no truncation."""
        uid = "alice_cap_exactly_10"
        seed_user(db, uid)
        service = make_journal_service(db)

        for i in range(10):
            service.create_entry(uid, make_match_request(title=f"Match {i}"))

        user = get_user_doc(db, uid)
        recent = user.get("journalRecent", [])
        assert len(recent) == 10


# ---------------------------------------------------------------------------
# IT-01-6: North Star goal persistence
# ---------------------------------------------------------------------------


class TestNorthStarGoal:
    def test_set_north_star_written_to_user_doc(self, db):
        """set_north_star writes northStarGoal to the user document."""
        uid = "alice_north_star"
        seed_user(db, uid)
        service = make_journal_service(db)

        result = service.set_north_star(uid, "Win 10 matches this month")

        assert result.goal_text == "Win 10 matches this month"
        assert result.progress_pct == 0.0

        user = get_user_doc(db, uid)
        goal = user.get("northStarGoal", {})
        assert goal["goalText"] == "Win 10 matches this month"
        assert goal["progressPct"] == 0.0
        assert "createdAt" in goal

    def test_get_north_star_reads_from_user_doc(self, db):
        """get_north_star returns the goal that was previously set."""
        uid = "alice_get_north_star"
        seed_user(db, uid)
        service = make_journal_service(db)

        service.set_north_star(uid, "Reduce double faults")
        result = service.get_north_star(uid)

        assert result is not None
        assert result.goal_text == "Reduce double faults"

    def test_set_north_star_overwrites_previous_goal(self, db):
        """Setting a new goal replaces the previous one."""
        uid = "alice_overwrite_goal"
        seed_user(db, uid)
        service = make_journal_service(db)

        service.set_north_star(uid, "First goal")
        service.set_north_star(uid, "New goal")

        result = service.get_north_star(uid)
        assert result.goal_text == "New goal"

    def test_get_north_star_returns_none_when_unset(self, db):
        """A user with no goal set returns None (routed to 404)."""
        uid = "alice_no_goal"
        seed_user(db, uid)
        service = make_journal_service(db)

        assert service.get_north_star(uid) is None

    def test_set_north_star_persists_client_progress(self, db):
        """A client-supplied progress_pct is stored and read back."""
        uid = "alice_progress_set"
        seed_user(db, uid)
        service = make_journal_service(db)

        result = service.set_north_star(uid, "Reach 4.5", progress_pct=55.0)

        assert result.progress_pct == 55.0
        assert get_user_doc(db, uid)["northStarGoal"]["progressPct"] == 55.0
        assert service.get_north_star(uid).progress_pct == 55.0

    def test_set_north_star_preserves_progress_on_text_only_update(self, db):
        """Omitting progress_pct on a later update preserves the stored value."""
        uid = "alice_progress_preserved"
        seed_user(db, uid)
        service = make_journal_service(db)

        service.set_north_star(uid, "Original goal", progress_pct=70.0)
        result = service.set_north_star(uid, "Reworded goal")

        assert result.goal_text == "Reworded goal"
        assert result.progress_pct == 70.0
        assert service.get_north_star(uid).progress_pct == 70.0

    def test_set_north_star_missing_user_raises(self, db):
        """set_north_star on a non-existent user raises ValueError."""
        service = make_journal_service(db)

        with pytest.raises(ValueError, match="User not found"):
            service.set_north_star("ghost_no_user", "Win it all")


# ---------------------------------------------------------------------------
# EX-01/02/03 integration coverage
# ---------------------------------------------------------------------------


class TestOwnershipAndSoftDelete:
    def test_cross_user_get_returns_none(self, db):
        """Another user's entry is invisible (returns None → 404)."""
        owner_uid = "owner_invisible"
        other_uid = "other_invisible"
        seed_user(db, owner_uid)
        seed_user(db, other_uid)
        service = make_journal_service(db)

        create_resp = service.create_entry(
            owner_uid, make_match_request(title="Owner entry")
        )

        # Cross-user get returns None (entry is scoped to owner's subcollection)
        assert service.get_entry(other_uid, create_resp.entry_id) is None

    def test_cross_user_update_returns_not_found(self, db):
        """Updating another user's entry raises not-found."""
        owner_uid = "owner_update_nf"
        other_uid = "other_update_nf"
        seed_user(db, owner_uid)
        seed_user(db, other_uid)
        service = make_journal_service(db)

        create_resp = service.create_entry(
            owner_uid, make_match_request(title="Owner entry")
        )

        with pytest.raises(ValueError, match="not found"):
            service.update_entry(
                other_uid,
                create_resp.entry_id,
                UpdateJournalEntryRequest(tags=["forbidden"]),
            )

    def test_cursor_referencing_other_users_entry_is_invalid(self, db):
        """A forged cursor entry_id from another user is rejected as invalid."""
        owner_uid = "owner_cursor_invalid"
        other_uid = "other_cursor_invalid"
        seed_user(db, owner_uid)
        seed_user(db, other_uid)
        service = make_journal_service(db)

        created = service.create_entry(
            owner_uid, make_match_request(title="Owner entry")
        )
        owner_entry = service.get_entry(owner_uid, created.entry_id)
        assert owner_entry is not None

        cursor = {"createdAt": owner_entry.created_at, "entryId": owner_entry.entry_id}
        with pytest.raises(JournalInvalidCursorError, match="Invalid cursor"):
            service.list_entries(other_uid, limit=2, cursor=cursor)

    def test_soft_delete_hides_entry_but_keeps_document(self, db):
        """Soft-deleted entries are hidden from reads/lists but remain in Firestore."""
        uid = "soft_delete_user"
        seed_user(db, uid)
        service = make_journal_service(db)
        repo = JournalRepo(db)

        created = service.create_entry(uid, make_match_request(title="Delete me"))
        service.delete_entry(uid, created.entry_id)

        # Hidden from normal reads
        assert service.get_entry(uid, created.entry_id) is None
        ids = {entry.entry_id for entry in service.list_entries(uid, limit=20)}
        assert created.entry_id not in ids

        # Still present canonically for recovery/audit
        deleted_entry = repo.get_entry(uid, created.entry_id, include_deleted=True)
        assert deleted_entry is not None
        assert deleted_entry.is_deleted is True
        assert deleted_entry.deleted_at is not None


class TestIdempotentCreate:
    def test_client_request_id_returns_existing_entry(self, db):
        """Same client_request_id for same user returns existing entry id."""
        uid = "idempotent_user"
        seed_user(db, uid)
        service = make_journal_service(db)

        req = make_match_request(title="Idempotent", client_request_id="req-1")
        first = service.create_entry(uid, req)
        second = service.create_entry(uid, req)

        assert first.entry_id == second.entry_id

        docs = list(
            db.collection("users").document(uid).collection("journalEntries").stream()
        )
        assert len(docs) == 1

    def test_client_request_id_is_scoped_per_user(self, db):
        """Different users can reuse same client_request_id without collisions."""
        uid_a = "idempotent_user_a"
        uid_b = "idempotent_user_b"
        seed_user(db, uid_a)
        seed_user(db, uid_b)
        service = make_journal_service(db)

        req = make_match_request(title="Scoped", client_request_id="same-id")
        first = service.create_entry(uid_a, req)
        second = service.create_entry(uid_b, req)

        assert first.entry_id != second.entry_id
