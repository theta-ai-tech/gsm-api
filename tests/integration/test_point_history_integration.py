"""
Integration tests for PointHistoryRepo.

Tests verify write and read behaviour against the real Firestore emulator,
including add_entry, paginated list_entries, and transactional writes.

Requires: FIRESTORE_EMULATOR_HOST env var set (e.g. via `make emu-all`)
"""

from datetime import datetime, timedelta, timezone

import pytest
from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.enums import PointHistoryReasonEnum, SportEnum, TierEnum
from app.models.point_history import PointHistoryEntry
from app.repos.point_history_repo import PointHistoryRepo

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_entry(
    sport: SportEnum = SportEnum.TENNIS,
    pts: int = 1500,
    delta: int = 100,
    reason: PointHistoryReasonEnum = PointHistoryReasonEnum.MATCH_WIN,
    created_at: datetime | None = None,
    **kwargs,
) -> PointHistoryEntry:
    return PointHistoryEntry(
        entry_id="",  # set by repo on write
        sport=sport,
        pts=pts,
        delta=delta,
        reason=reason,
        created_at=created_at or datetime.now(timezone.utc),
        **kwargs,
    )


def seed_user(db, uid: str) -> None:
    db.collection("users").document(uid).set({"name": uid, "email": f"{uid}@test.com"})


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_point_history(db):
    """Delete pointHistory subcollections after each test."""
    yield
    for user_doc in db.collection("users").stream():
        for entry_doc in user_doc.reference.collection("pointHistory").stream():
            entry_doc.reference.delete()


# ---------------------------------------------------------------------------
# PH-01: add_entry writes correct fields
# ---------------------------------------------------------------------------


class TestAddEntry:
    def test_entry_written_with_correct_fields(self, db):
        """add_entry writes all expected camelCase fields to Firestore."""
        uid = "ph_add_fields"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)
        now = datetime.now(timezone.utc)

        entry = make_entry(
            sport=SportEnum.TENNIS,
            pts=2250,
            delta=150,
            reason=PointHistoryReasonEnum.MATCH_WIN,
            match_id="match_789",
            opponent_uid="user_456",
            opponent_pts_before=3100,
            tier_before=TierEnum.INTERMEDIATE,
            tier_after=TierEnum.INTERMEDIATE,
            created_at=now,
        )
        entry_id = repo.add_entry(uid, entry)

        doc = (
            db.collection("users")
            .document(uid)
            .collection("pointHistory")
            .document(entry_id)
            .get()
        )
        assert doc.exists
        data = doc.to_dict()
        assert data["sport"] == "tennis"
        assert data["pts"] == 2250
        assert data["delta"] == 150
        assert data["reason"] == "match_win"
        assert data["matchId"] == "match_789"
        assert data["opponentUid"] == "user_456"
        assert data["opponentPtsBefore"] == 3100
        assert data["tierBefore"] == "intermediate"
        assert data["tierAfter"] == "intermediate"
        assert "createdAt" in data

    def test_add_entry_returns_generated_id(self, db):
        """add_entry returns a non-empty auto-generated document ID."""
        uid = "ph_add_id"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)

        entry_id = repo.add_entry(uid, make_entry())

        assert isinstance(entry_id, str)
        assert len(entry_id) > 0

    def test_optional_fields_written_as_none(self, db):
        """Optional fields (matchId, leagueId, etc.) are stored as None when not set."""
        uid = "ph_add_optional_none"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)

        entry_id = repo.add_entry(
            uid, make_entry(reason=PointHistoryReasonEnum.ADMIN_ADJUSTMENT)
        )

        data = (
            db.collection("users")
            .document(uid)
            .collection("pointHistory")
            .document(entry_id)
            .get()
            .to_dict()
        )
        assert data["matchId"] is None
        assert data["opponentUid"] is None
        assert data["tierBefore"] is None
        assert data["tierAfter"] is None


# ---------------------------------------------------------------------------
# PH-02: list_entries — sport filter and ordering
# ---------------------------------------------------------------------------


class TestListEntries:
    def test_list_returns_entries_for_sport(self, db):
        """list_entries filters by sport and returns the correct entries."""
        uid = "ph_list_sport_filter"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)

        repo.add_entry(uid, make_entry(sport=SportEnum.TENNIS))
        repo.add_entry(uid, make_entry(sport=SportEnum.PADEL))
        repo.add_entry(uid, make_entry(sport=SportEnum.TENNIS))

        entries = repo.list_entries(uid, SportEnum.TENNIS)

        assert len(entries) == 2
        assert all(e.sport == SportEnum.TENNIS for e in entries)

    def test_list_returns_entries_newest_first(self, db):
        """list_entries returns entries ordered by createdAt DESC."""
        uid = "ph_list_order"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)
        base = datetime.now(timezone.utc)

        repo.add_entry(uid, make_entry(pts=1000, created_at=base - timedelta(hours=2)))
        repo.add_entry(uid, make_entry(pts=1100, created_at=base - timedelta(hours=1)))
        repo.add_entry(uid, make_entry(pts=1200, created_at=base))

        entries = repo.list_entries(uid, SportEnum.TENNIS, limit=10)

        assert entries[0].pts == 1200
        assert entries[1].pts == 1100
        assert entries[2].pts == 1000

    def test_list_respects_limit(self, db):
        """limit parameter restricts the number of entries returned."""
        uid = "ph_list_limit"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)

        for i in range(5):
            repo.add_entry(uid, make_entry(pts=1000 + i * 10))

        entries = repo.list_entries(uid, SportEnum.TENNIS, limit=3)

        assert len(entries) == 3

    def test_list_empty_for_new_user(self, db):
        """A user with no history returns an empty list."""
        uid = "ph_list_empty"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)

        entries = repo.list_entries(uid, SportEnum.TENNIS)

        assert entries == []

    def test_list_maps_model_fields_correctly(self, db):
        """Returned PointHistoryEntry has correct field values."""
        uid = "ph_list_model"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)

        repo.add_entry(
            uid,
            make_entry(
                pts=2500,
                delta=-200,
                reason=PointHistoryReasonEnum.MATCH_LOSS,
                match_id="m_abc",
                tier_before=TierEnum.ADVANCED,
                tier_after=TierEnum.INTERMEDIATE,
            ),
        )

        entries = repo.list_entries(uid, SportEnum.TENNIS)

        assert len(entries) == 1
        e = entries[0]
        assert e.pts == 2500
        assert e.delta == -200
        assert e.reason == PointHistoryReasonEnum.MATCH_LOSS
        assert e.match_id == "m_abc"
        assert e.tier_before == TierEnum.ADVANCED
        assert e.tier_after == TierEnum.INTERMEDIATE


# ---------------------------------------------------------------------------
# PH-03: cursor-based pagination
# ---------------------------------------------------------------------------


class TestListEntriesPagination:
    def test_cursor_advances_to_next_page(self, db):
        """Cursor returned from page 1 fetches a non-overlapping page 2."""
        uid = "ph_pagination"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)
        base = datetime.now(timezone.utc)

        for i in range(5):
            repo.add_entry(
                uid,
                make_entry(pts=1000 + i * 10, created_at=base + timedelta(seconds=i)),
            )

        page1 = repo.list_entries(uid, SportEnum.TENNIS, limit=2)
        assert len(page1) == 2

        cursor = {"createdAt": page1[-1].created_at, "entryId": page1[-1].entry_id}
        page2 = repo.list_entries(uid, SportEnum.TENNIS, limit=2, cursor=cursor)
        assert len(page2) >= 1

        page1_ids = {e.entry_id for e in page1}
        page2_ids = {e.entry_id for e in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_last_page_returns_remaining_entries(self, db):
        """After paginating through all entries the final page is empty."""
        uid = "ph_pagination_exhaust"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)
        base = datetime.now(timezone.utc)

        for i in range(3):
            repo.add_entry(
                uid, make_entry(pts=1000 + i, created_at=base + timedelta(seconds=i))
            )

        page1 = repo.list_entries(uid, SportEnum.TENNIS, limit=3)
        assert len(page1) == 3

        cursor = {"createdAt": page1[-1].created_at, "entryId": page1[-1].entry_id}
        page2 = repo.list_entries(uid, SportEnum.TENNIS, limit=3, cursor=cursor)
        assert page2 == []


# ---------------------------------------------------------------------------
# PH-04: transactional write
# ---------------------------------------------------------------------------


class TestAddEntryInTransaction:
    def test_transactional_write_commits_entry(self, db):
        """add_entry_in_transaction writes the entry when the transaction commits."""
        uid = "ph_txn_commit"
        seed_user(db, uid)
        repo = PointHistoryRepo(db)

        entry = make_entry(
            pts=1800, delta=50, reason=PointHistoryReasonEnum.TIER_REBALANCE
        )

        @firestore.transactional
        def _txn(transaction):
            return repo.add_entry_in_transaction(transaction, uid, entry)

        doc_ref = _txn(db.transaction())

        doc = doc_ref.get()
        assert doc.exists
        data = doc.to_dict()
        assert data["pts"] == 1800
        assert data["delta"] == 50
        assert data["reason"] == "tier_rebalance"
